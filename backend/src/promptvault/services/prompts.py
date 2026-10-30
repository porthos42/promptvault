"""Prompt CRUD, revisions, trash, bulk actions and rendering."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from promptvault.models import Category, Prompt, PromptRevision, Tag
from promptvault.services import categories as cat_svc
from promptvault.services import tags as tag_svc
from promptvault.services import variables as var_svc
from promptvault.services.errors import ConflictError, NotFoundError, ValidationFailed

CONTENT_FIELDS = (
    "title",
    "body",
    "description",
    "model_hints",
    "output_format",
    "difficulty",
    "prompt_type",
    "disclaimer",
    "source",
    "source_url",
    "license",
)


def _now() -> datetime:
    return datetime.now(UTC)


def body_hash(body: str) -> str:
    return hashlib.sha256(" ".join(body.split()).encode()).hexdigest()


def snapshot(prompt: Prompt) -> dict[str, Any]:
    """The versioned content of a prompt (what a revision stores)."""
    snap: dict[str, Any] = {f: getattr(prompt, f) for f in CONTENT_FIELDS}
    snap["category"] = prompt.category.slug if prompt.category else None
    snap["tags"] = sorted(t.name for t in prompt.tags)
    snap["variables"] = prompt.variables
    return snap


def _next_version(session: Session, prompt_id: str) -> int:
    cur = session.scalar(
        select(func.max(PromptRevision.version)).where(PromptRevision.prompt_id == prompt_id)
    )
    return (cur or 0) + 1


def current_version(session: Session, prompt_id: str) -> int:
    return _next_version(session, prompt_id) - 1


def _add_revision(session: Session, prompt: Prompt) -> None:
    session.add(
        PromptRevision(
            prompt_id=prompt.id,
            version=_next_version(session, prompt.id),
            snapshot=snapshot(prompt),
        )
    )
    session.flush()


def _load(stmt: Any) -> Any:
    return stmt.options(joinedload(Prompt.category), selectinload(Prompt.tags))


def get_prompt(session: Session, prompt_id: str) -> Prompt:
    p: Prompt | None = session.scalar(_load(select(Prompt).where(Prompt.id == prompt_id)))
    if p is None:
        raise NotFoundError(f"Prompt '{prompt_id}' not found")
    return p


def resolve_prompt(session: Session, ident: str) -> Prompt:
    """Find by full id, or by a unique id prefix (>= 4 chars)."""
    p: Prompt | None = session.scalar(_load(select(Prompt).where(Prompt.id == ident)))
    if p is not None:
        return p
    if len(ident) >= 4:
        matches: list[Prompt] = list(
            session.scalars(_load(select(Prompt).where(Prompt.id.like(ident + "%")).limit(2)))
        )
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ConflictError(f"'{ident}' matches more than one prompt; use more characters")
    raise NotFoundError(f"Prompt '{ident}' not found")


def _apply(session: Session, prompt: Prompt, data: dict[str, Any]) -> None:
    if "category" in data:
        slug = data["category"]
        prompt.category = cat_svc.get_by_slug(session, slug) if slug else None
    for f in CONTENT_FIELDS:
        if f in data and not (data[f] is None and f in ("title", "body")):
            setattr(prompt, f, data[f])
    if "tags" in data and data["tags"] is not None:
        prompt.tags = tag_svc.get_or_create(session, data["tags"])
    if "is_favorite" in data and data["is_favorite"] is not None:
        prompt.is_favorite = data["is_favorite"]
    if "rating" in data:
        prompt.rating = data["rating"]
    declared = (
        [v if isinstance(v, dict) else v.model_dump() for v in data["variables"]]
        if data.get("variables") is not None
        else prompt.variables
    )
    prompt.variables = var_svc.merge_variables(prompt.body, declared)
    prompt.body_hash = body_hash(prompt.body)


def create_prompt(session: Session, data: dict[str, Any]) -> Prompt:
    prompt = Prompt(title=data["title"], body=data["body"], variables=[])
    session.add(prompt)
    _apply(session, prompt, data)
    session.flush()
    session.refresh(prompt, ["category", "tags"])
    _add_revision(session, prompt)
    return prompt


def update_prompt(session: Session, prompt: Prompt, data: dict[str, Any]) -> Prompt:
    before = snapshot(prompt)
    _apply(session, prompt, data)
    session.flush()
    session.refresh(prompt, ["category", "tags"])
    prompt.updated_at = _now()
    if snapshot(prompt) != before:
        _add_revision(session, prompt)
    session.flush()
    return prompt


def duplicate_prompt(session: Session, prompt: Prompt) -> Prompt:
    data = snapshot(prompt)
    data["title"] = f"{prompt.title} (copy)"[:300]
    data["source"] = "user"
    data["is_favorite"] = False
    return create_prompt(session, data)


# ---- trash -------------------------------------------------------------------------------


def trash_prompt(session: Session, prompt: Prompt) -> None:
    if prompt.deleted_at is None:
        prompt.deleted_at = _now()
        session.flush()


def restore_prompt(session: Session, prompt: Prompt) -> Prompt:
    prompt.deleted_at = None
    session.flush()
    return prompt


def delete_permanently(session: Session, prompt: Prompt) -> None:
    if prompt.deleted_at is None:
        raise ConflictError("Move the prompt to Trash before deleting it permanently")
    session.delete(prompt)
    session.flush()


def purge_trash(session: Session, older_than_days: int | None = None) -> int:
    stmt = select(Prompt).where(Prompt.deleted_at.is_not(None))
    if older_than_days is not None:
        stmt = stmt.where(Prompt.deleted_at < _now() - timedelta(days=older_than_days))
    victims = session.scalars(stmt).all()
    for p in victims:
        session.delete(p)
    session.flush()
    return len(victims)


# ---- revisions ---------------------------------------------------------------------------


def list_revisions(session: Session, prompt: Prompt) -> list[PromptRevision]:
    return list(
        session.scalars(
            select(PromptRevision)
            .where(PromptRevision.prompt_id == prompt.id)
            .order_by(PromptRevision.version.desc())
        )
    )


def restore_revision(session: Session, prompt: Prompt, version: int) -> Prompt:
    rev = session.scalar(
        select(PromptRevision).where(
            PromptRevision.prompt_id == prompt.id, PromptRevision.version == version
        )
    )
    if rev is None:
        raise NotFoundError(f"Revision {version} not found")
    snap = dict(rev.snapshot)
    slug = snap.get("category")
    if slug and session.scalar(select(Category.id).where(Category.slug == slug)) is None:
        snap["category"] = None  # category was deleted since
    return update_prompt(session, prompt, snap)


# ---- listing -----------------------------------------------------------------------------


@dataclass
class ListFilters:
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    tags_mode: str = "all"
    difficulty: str | None = None
    prompt_type: str | None = None
    favorite: bool | None = None
    source: str | None = None
    trash: bool = False


def _encode_cursor(p: Prompt) -> str:
    raw = f"{p.updated_at.isoformat()}|{p.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts, pid = raw.split("|", 1)
        return datetime.fromisoformat(ts), pid
    except Exception as exc:
        raise ValidationFailed("Invalid cursor") from exc


def list_prompts(
    session: Session, f: ListFilters, limit: int = 50, cursor: str | None = None
) -> tuple[list[Prompt], int, str | None]:
    conds: list[Any] = [Prompt.deleted_at.is_not(None) if f.trash else Prompt.deleted_at.is_(None)]
    if f.category:
        root = cat_svc.get_by_slug(session, f.category)
        conds.append(Prompt.category_id.in_(cat_svc.descendant_ids(session, root)))
    tags = tag_svc.normalize_many(f.tags)
    if tags:
        if f.tags_mode == "any":
            conds.append(Prompt.tags.any(Tag.name.in_(tags)))
        else:
            conds.extend(Prompt.tags.any(Tag.name == t) for t in tags)
    if f.difficulty:
        conds.append(Prompt.difficulty == f.difficulty)
    if f.prompt_type:
        conds.append(Prompt.prompt_type == f.prompt_type)
    if f.favorite is not None:
        conds.append(Prompt.is_favorite.is_(f.favorite))
    if f.source:
        conds.append(Prompt.source == f.source)

    total = session.scalar(select(func.count()).select_from(Prompt).where(*conds)) or 0
    page_conds = list(conds)
    if cursor:
        ts, pid = _decode_cursor(cursor)
        page_conds.append(
            or_(Prompt.updated_at < ts, and_(Prompt.updated_at == ts, Prompt.id < pid))
        )
    rows = list(
        session.scalars(
            _load(
                select(Prompt)
                .where(*page_conds)
                .order_by(Prompt.updated_at.desc(), Prompt.id.desc())
                .limit(limit + 1)
            )
        )
    )
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return rows[:limit], total, next_cursor


# ---- bulk --------------------------------------------------------------------------------


def bulk_apply(
    session: Session,
    ids: list[str],
    action: str,
    tags: list[str],
    category: str | None,
) -> tuple[int, list[str]]:
    found = {p.id: p for p in session.scalars(_load(select(Prompt).where(Prompt.id.in_(ids))))}
    not_found = [i for i in ids if i not in found]
    cat = cat_svc.get_by_slug(session, category) if action == "set_category" and category else None
    add_tags = tag_svc.get_or_create(session, tags) if action == "add_tags" else []
    drop = set(tag_svc.normalize_many(tags)) if action == "remove_tags" else set()
    if action in ("add_tags", "remove_tags") and not tags:
        raise ValidationFailed("'tags' is required for this action")
    for p in found.values():
        if action == "add_tags":
            p.tags = [*p.tags, *[t for t in add_tags if t not in p.tags]]
        elif action == "remove_tags":
            p.tags = [t for t in p.tags if t.name not in drop]
        elif action == "set_category":
            p.category = cat
        elif action in ("favorite", "unfavorite"):
            p.is_favorite = action == "favorite"
        elif action == "delete":
            trash_prompt(session, p)
        elif action == "restore":
            p.deleted_at = None
        p.updated_at = _now()
    session.flush()
    return len(found), not_found


# ---- render ------------------------------------------------------------------------------


def render_prompt(prompt: Prompt, values: dict[str, Any]) -> tuple[str, list[str]]:
    return var_svc.render(prompt.body, prompt.variables, values)
