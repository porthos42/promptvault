from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status

from promptvault.api.deps import DB
from promptvault.models import Prompt
from promptvault.schemas import (
    BulkOut,
    BulkRequest,
    CategoryRef,
    PromptCreate,
    PromptList,
    PromptOut,
    PromptPatch,
    PurgeOut,
    RenderOut,
    RenderRequest,
    RevisionOut,
)
from promptvault.services import prompts as svc

router = APIRouter(tags=["prompts"])


def to_out(p: Prompt, version: int | None = None) -> PromptOut:
    return PromptOut(
        id=p.id,
        seed_id=p.seed_id,
        title=p.title,
        body=p.body,
        description=p.description,
        category=CategoryRef(slug=p.category.slug, name=p.category.name) if p.category else None,
        tags=sorted(t.name for t in p.tags),
        variables=p.variables,
        model_hints=p.model_hints,
        output_format=p.output_format,
        difficulty=p.difficulty,
        prompt_type=p.prompt_type,
        disclaimer=p.disclaimer,
        source=p.source,
        source_url=p.source_url,
        license=p.license,
        is_favorite=p.is_favorite,
        rating=p.rating,
        use_count=p.use_count,
        version=version,
        created_at=p.created_at,
        updated_at=p.updated_at,
        deleted_at=p.deleted_at,
    )


@router.get("/prompts", response_model=PromptList)
def list_prompts(
    db: DB,
    category: str | None = None,
    tags: Annotated[list[str] | None, Query()] = None,
    tags_mode: Literal["all", "any"] = "all",
    difficulty: Literal["beginner", "intermediate", "advanced"] | None = None,
    prompt_type: Literal["system", "user", "template", "chain"] | None = None,
    favorite: bool | None = None,
    source: str | None = None,
    trash: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> PromptList:
    filters = svc.ListFilters(
        category=category,
        tags=tags or [],
        tags_mode=tags_mode,
        difficulty=difficulty,
        prompt_type=prompt_type,
        favorite=favorite,
        source=source,
        trash=trash,
    )
    rows, total, nxt = svc.list_prompts(db, filters, limit, cursor)
    return PromptList(items=[to_out(p) for p in rows], total=total, next_cursor=nxt)


@router.post("/prompts", response_model=PromptOut, status_code=status.HTTP_201_CREATED)
def create_prompt(body: PromptCreate, db: DB, response: Response) -> PromptOut:
    p = svc.create_prompt(db, body.model_dump())
    response.headers["Location"] = f"/api/v1/prompts/{p.id}"
    return to_out(p, svc.current_version(db, p.id))


# Fixed paths must be declared before /prompts/{prompt_id}.
@router.post("/prompts/bulk", response_model=BulkOut)
def bulk(body: BulkRequest, db: DB) -> BulkOut:
    affected, missing = svc.bulk_apply(db, body.ids, body.action, body.tags, body.category)
    return BulkOut(affected=affected, not_found=missing)


@router.delete("/trash", response_model=PurgeOut)
def purge_trash(db: DB, older_than_days: Annotated[int | None, Query(ge=0)] = None) -> PurgeOut:
    """Permanently delete everything in Trash (optionally only items older than N days)."""
    return PurgeOut(purged=svc.purge_trash(db, older_than_days))


@router.get("/prompts/{prompt_id}", response_model=PromptOut)
def get_prompt(prompt_id: str, db: DB) -> PromptOut:
    p = svc.get_prompt(db, prompt_id)
    return to_out(p, svc.current_version(db, p.id))


@router.put("/prompts/{prompt_id}", response_model=PromptOut)
def replace_prompt(prompt_id: str, body: PromptCreate, db: DB) -> PromptOut:
    p = svc.update_prompt(db, svc.get_prompt(db, prompt_id), body.model_dump())
    return to_out(p, svc.current_version(db, p.id))


@router.patch("/prompts/{prompt_id}", response_model=PromptOut)
def patch_prompt(prompt_id: str, body: PromptPatch, db: DB) -> PromptOut:
    p = svc.update_prompt(db, svc.get_prompt(db, prompt_id), body.model_dump(exclude_unset=True))
    return to_out(p, svc.current_version(db, p.id))


@router.delete("/prompts/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(prompt_id: str, db: DB, permanent: bool = False) -> Response:
    """Soft delete (move to Trash). `permanent=true` removes a trashed prompt for good."""
    p = svc.get_prompt(db, prompt_id)
    if permanent:
        svc.delete_permanently(db, p)
    else:
        svc.trash_prompt(db, p)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/prompts/{prompt_id}/restore", response_model=PromptOut)
def restore_prompt(prompt_id: str, db: DB) -> PromptOut:
    p = svc.restore_prompt(db, svc.get_prompt(db, prompt_id))
    return to_out(p, svc.current_version(db, p.id))


@router.post(
    "/prompts/{prompt_id}/duplicate", response_model=PromptOut, status_code=status.HTTP_201_CREATED
)
def duplicate_prompt(prompt_id: str, db: DB) -> PromptOut:
    p = svc.duplicate_prompt(db, svc.get_prompt(db, prompt_id))
    return to_out(p, svc.current_version(db, p.id))


@router.get("/prompts/{prompt_id}/revisions", response_model=list[RevisionOut])
def list_revisions(prompt_id: str, db: DB) -> list[RevisionOut]:
    revs = svc.list_revisions(db, svc.get_prompt(db, prompt_id))
    return [
        RevisionOut(version=r.version, created_at=r.created_at, snapshot=r.snapshot) for r in revs
    ]


@router.post("/prompts/{prompt_id}/revisions/{version}/restore", response_model=PromptOut)
def restore_revision(prompt_id: str, version: int, db: DB) -> PromptOut:
    p = svc.restore_revision(db, svc.get_prompt(db, prompt_id), version)
    return to_out(p, svc.current_version(db, p.id))


@router.post("/prompts/{prompt_id}/render", response_model=RenderOut)
def render(prompt_id: str, body: RenderRequest, db: DB) -> RenderOut:
    p = svc.get_prompt(db, prompt_id)
    text, missing = svc.render_prompt(p, body.values)
    return RenderOut(rendered=text, missing=missing, variables=p.variables)
