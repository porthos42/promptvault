"""Import endpoints: preview (dry run), commit (job) and job progress (JSON + SSE)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from promptvault import importers
from promptvault.api.deps import DB
from promptvault.importers import jobs, pipeline
from promptvault.schemas import (
    CommitRequest,
    DraftOut,
    ImporterOut,
    ImportRequest,
    JobOut,
    MatchOut,
    PreviewOut,
    PreviewRow,
)
from promptvault.services.errors import PayloadTooLarge, ValidationFailed

router = APIRouter(tags=["import"])

INLINE_MAX_ROWS = 25  # commits up to this size run inside the request; larger ones are jobs
POLL_SECONDS = 0.1
KEEPALIVE_SECONDS = 15.0

M = TypeVar("M", bound=BaseModel)


async def capped_body(request: Request) -> bytes:
    """Raw request body, refused with 413 once it exceeds the configured cap (also if chunked)."""
    limit: int = request.app.state.settings.import_max_payload_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise PayloadTooLarge(f"Request body exceeds {limit} bytes")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise PayloadTooLarge(f"Request body exceeds {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


Body = Annotated[bytes, Depends(capped_body)]


def _parse(model: type[M], raw: bytes) -> M:
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'body'}: {e['msg']}" for e in exc.errors()[:10]
        )
        raise ValidationFailed(detail) from exc


def _max_rows(request: Request) -> int:
    return int(request.app.state.settings.import_max_rows)


def _runner(request: Request) -> jobs.JobRunner:
    runner: jobs.JobRunner = request.app.state.job_runner
    return runner


def _defaults(req: ImportRequest) -> pipeline.Defaults:
    return pipeline.Defaults(license=req.default_license, source_url=req.default_source_url)


def _preview_row(r: pipeline.Row) -> PreviewRow:
    d = r.draft.to_dict()
    return PreviewRow(
        index=r.index,
        status=r.status,
        errors=d.pop("errors"),
        warnings=d.pop("warnings"),
        needs_license_confirm=r.needs_license_confirm,
        draft=DraftOut(**d),
        match=MatchOut(
            kind=r.match.kind,
            score=round(r.match.score, 4),
            title=r.match.title,
            prompt_id=r.match.prompt_id,
            batch_index=r.match.batch_index,
        )
        if r.match
        else None,
    )


@router.get("/import/importers", response_model=list[ImporterOut])
def list_importers() -> list[ImporterOut]:
    """Registered importers, including ones that need an optional extra."""
    return [ImporterOut(**i) for i in importers.registry.describe()]


@router.post("/import/preview", response_model=PreviewOut)
def preview(request: Request, db: DB, raw: Body) -> PreviewOut:
    """Dry run: parse, normalize, validate and dedupe. Writes nothing."""
    req = _parse(ImportRequest, raw)
    rows = pipeline.preview(db, req.importer, req.source, _max_rows(request), _defaults(req))
    return PreviewOut(
        importer=req.importer,
        total=len(rows),
        new=sum(r.status == "new" for r in rows),
        duplicate=sum(r.status == "duplicate" for r in rows),
        invalid=sum(r.status == "invalid" for r in rows),
        needs_license_confirm=sum(r.needs_license_confirm and r.status != "invalid" for r in rows),
        rows=[_preview_row(r) for r in rows],
    )


@router.post("/import/commit", response_model=JobOut)
def commit(request: Request, db: DB, raw: Body, response: Response) -> JobOut:
    """Import the rows. Small imports finish inside the request (200); larger ones return a
    pending job (202) to follow with GET /jobs/{id} or its SSE stream."""
    req = _parse(CommitRequest, raw)
    rows = pipeline.analyze(db, req.importer, req.source, _max_rows(request), _defaults(req))
    options = pipeline.CommitOptions(
        default_action=req.default_action,
        actions=req.actions,
        confirm_license=req.confirm_license,
        confirmed_rows=frozenset(req.confirmed_rows),
    )
    job = jobs.create_job(db, req.importer, pipeline.plan(rows, options))
    db.commit()
    runner = _runner(request)
    if len(rows) <= INLINE_MAX_ROWS:
        runner.run_now(db, job.id)
    else:
        runner.submit(job.id)
        response.status_code = 202
    return JobOut(**runner.view(job.id, results=True))


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, request: Request) -> JobOut:
    return JobOut(**_runner(request).view(job_id, results=True))


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data))}\n\n"


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    """Server-sent events: `progress` whenever counters change, then one `done` or `failed`."""
    runner = _runner(request)
    await run_in_threadpool(runner.view, job_id)  # 404 before the stream starts

    async def stream() -> AsyncIterator[str]:
        last: tuple[Any, ...] | None = None
        idle = 0.0
        while True:
            state = await run_in_threadpool(runner.view, job_id)
            key = (state["status"], *(state[k] for k in jobs.COUNTERS))
            if key != last:
                yield _sse("progress", state)
                last, idle = key, 0.0
            if state["status"] in jobs.TERMINAL:
                yield _sse(state["status"], state)
                return
            await asyncio.sleep(POLL_SECONDS)
            idle += POLL_SECONDS
            if idle >= KEEPALIVE_SECONDS:
                yield ": keepalive\n\n"
                idle = 0.0

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
