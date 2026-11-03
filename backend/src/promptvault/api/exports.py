"""Export endpoints: downloads in four formats, single-prompt export and the share snippet."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse

from promptvault.api.deps import DB
from promptvault.schemas import ExportFilters, ExportFormatOut, ExportRequest, ShareOut
from promptvault.services import export as export_svc
from promptvault.services import prompts as svc
from promptvault.services.errors import NotFoundError

router = APIRouter(tags=["export"])

# Browsers hide custom headers from a separately hosted UI unless the CORS layer exposes them.
EXPOSED_HEADERS = ["Content-Disposition", "X-Export-Count", "X-Export-Missing", "X-Export-Warnings"]


def _selection(
    filters: ExportFilters, ids: list[str] | None, include_trashed: bool
) -> export_svc.Selection:
    return export_svc.Selection(
        filters=svc.ListFilters(
            q=filters.q,
            category=filters.category,
            tags=filters.tags,
            tags_mode=filters.tags_mode,
            difficulty=filters.difficulty,
            prompt_type=filters.prompt_type,
            favorite=filters.favorite,
            source=filters.source,
            model=filters.model,
            has_variables=filters.has_variables,
        ),
        ids=ids,
        include_trashed=include_trashed,
    )


def _respond(
    request: Request,
    db: DB,
    fmt: str,
    selection: export_svc.Selection,
    options: export_svc.Options,
    *,
    one: bool = False,
) -> Response:
    """Plan (and refuse oversized selections) before the first byte, then stream."""
    info = export_svc.get_format(fmt)
    plan = export_svc.prepare(db, selection, request.app.state.settings.export_max_rows)
    opener = request.app.state.session_factory
    headers = {
        "X-Export-Count": str(len(plan.ids)),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if plan.missing:
        headers["X-Export-Missing"] = str(len(plan.missing))
    if one:
        if not plan.ids:
            raise NotFoundError("Prompt not found")
        with opener() as session:
            rec = export_svc.load_records(session, plan.ids)[0]
        if info.name == "markdown":  # one prompt is a plain .md file, not a ZIP
            name = export_svc.single_name(rec, "md")
            headers["Content-Disposition"] = f'attachment; filename="{name}"'
            return Response(
                export_svc.markdown_text(rec).encode("utf-8"),
                media_type="text/markdown; charset=utf-8",
                headers=headers,
            )
        name = export_svc.single_name(rec, info.extension)
    else:
        name = export_svc.download_name(info)
    result = export_svc.run(opener, fmt, plan, options)
    headers["Content-Disposition"] = f'attachment; filename="{name}"'
    if result.warnings:
        headers["X-Export-Warnings"] = str(len(result.warnings))
    return StreamingResponse(result.chunks, media_type=info.media_type, headers=headers)


@router.get("/export/formats", response_model=list[ExportFormatOut])
def list_formats() -> list[ExportFormatOut]:
    """Export formats and whether they can run here (XLSX needs the optional extra)."""
    return [ExportFormatOut(**f) for f in export_svc.describe_formats()]


@router.get("/export")
def export_get(
    request: Request,
    db: DB,
    format: Annotated[str, Query(description="json, csv, xlsx or markdown (a ZIP)")],  # noqa: A002
    q: Annotated[str | None, Query(max_length=300)] = None,
    category: str | None = None,
    tags: Annotated[list[str] | None, Query()] = None,
    tags_mode: Literal["all", "any"] = "all",
    difficulty: Literal["beginner", "intermediate", "advanced"] | None = None,
    prompt_type: Literal["system", "user", "template", "chain"] | None = None,
    favorite: bool | None = None,
    source: str | None = None,
    model: str | None = None,
    has_variables: bool | None = None,
    ids: Annotated[list[str] | None, Query(min_length=1, max_length=500)] = None,
    include_trashed: bool = False,
    pretty: bool = False,
    bom: bool = True,
    raw: bool = False,
) -> Response:
    """Download the library (or a filtered part of it). Live prompts only unless
    `include_trashed`; ordered by title. Answers 413 above PV_EXPORT_MAX_ROWS prompts."""
    filters = ExportFilters(
        q=q,
        category=category,
        tags=tags or [],
        tags_mode=tags_mode,
        difficulty=difficulty,
        prompt_type=prompt_type,
        favorite=favorite,
        source=source,
        model=model,
        has_variables=has_variables,
    )
    return _respond(
        request,
        db,
        format,
        _selection(filters, ids, include_trashed),
        export_svc.Options(pretty=pretty, bom=bom, raw=raw),
    )


@router.post("/export")
def export_post(body: ExportRequest, request: Request, db: DB) -> Response:
    """Same as GET /export for selections too long for a query string (up to 500 ids)."""
    return _respond(
        request,
        db,
        body.format,
        _selection(body.filters, body.ids, body.include_trashed),
        export_svc.Options(pretty=body.pretty, bom=body.bom, raw=body.raw),
    )


@router.get("/prompts/{prompt_id}/export")
def export_prompt(
    prompt_id: str,
    request: Request,
    db: DB,
    format: Annotated[str, Query(description="json, csv, xlsx or markdown (one .md file)")],  # noqa: A002
    pretty: bool = False,
    bom: bool = True,
    raw: bool = False,
) -> Response:
    """Export one live prompt (404 for an unknown or trashed id)."""
    return _respond(
        request,
        db,
        format,
        export_svc.Selection(ids=[prompt_id]),
        export_svc.Options(pretty=pretty, bom=bom, raw=raw),
        one=True,
    )


@router.get("/prompts/{prompt_id}/share", response_model=ShareOut)
def share_prompt(
    prompt_id: str,
    db: DB,
    format: Annotated[Literal["markdown", "text", "json"], Query()] = "markdown",  # noqa: A002
    values: Annotated[
        list[str] | None, Query(description="Variable values as name=value (repeatable)")
    ] = None,
) -> ShareOut:
    """A copy-paste block for one prompt. With `values` the variables are filled in."""
    p = svc.get_prompt(db, prompt_id)
    if p.deleted_at is not None:
        raise NotFoundError(f"Prompt '{prompt_id}' not found")
    rec = export_svc.to_record(p, svc.current_version(db, p.id))
    text, missing = export_svc.share_snippet(rec, format, export_svc.parse_values(values))
    return ShareOut(format=format, text=text, missing=missing)
