"""Prompt CRUD, revisions, trash, bulk actions and rendering."""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Float, Integer, func, literal_column, or_, select, text, update
from sqlalchemy.orm import Session, joinedload, selectinload

from promptvault.models import Category, Prompt, PromptRevision, Tag
from promptvault.services import categories as cat_svc
from promptvault.services import search as search_svc
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

log = logging.getLogger(__name__)

SORTS = ("relevance", "newest", "updated", "recent", "popular", "rating", "title")


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
        prompt.tags_text = tag_svc.tags_text(prompt.tags)
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


# ---- listing / search --------------------------------------------------------------------


@dataclass
class ListFilters:
    q: str | None = None
    sort: str | None = None  # one of SORTS; default: relevance when q is set, else updated
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    tags_mode: str = "all"
    difficulty: str | None = None
    prompt_type: str | None = None
    favorite: bool | None = None
    source: str | None = None
    model: str | None = None  # substring of model_hints
    has_variables: bool | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    updated_after: datetime | None = None
    trash: bool = False


@dataclass
class ListResult:
    items: list[Prompt]
    total: int
    next_cursor: str | None
    sort: str
    corrected_query: str | None = None


def _encode_cursor(sort: str, offset: int) -> str:
    return base64.urlsafe_b64encode(f"{sort}:{offset}".encode()).decode()


def _decode_cursor(cursor: str, sort: str) -> int:
    try:
        c_sort, off = base64.urlsafe_b64decode(cursor.encode()).decode().split(":", 1)
        offset = int(off)
    except Exception as exc:
        raise ValidationFailed("Invalid cursor") from exc
    if c_sort != sort or offset < 0:
        raise ValidationFailed("Cursor does not match the requested sort")
    return offset


def _is_sqlite(session: Session) -> bool:
    return session.get_bind().dialect.name == "sqlite"


def _filter_conditions(session: Session, f: ListFilters) -> list[Any]:
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
    if f.model:
        conds.append(Prompt.model_hints.ilike(f"%{f.model}%"))
    if f.has_variables is not None:
        n = func.json_array_length(Prompt.variables)
        conds.append(n > 0 if f.has_variables else n == 0)
    if f.created_after:
        conds.append(Prompt.created_at >= f.created_after)
    if f.created_before:
        conds.append(Prompt.created_at < f.created_before)
    if f.updated_after:
        conds.append(Prompt.updated_at >= f.updated_after)
    return conds


def _order_by(sort: str, rank: Any) -> list[Any]:
    by: dict[str, list[Any]] = {
        "newest": [Prompt.created_at.desc()],
        "updated": [Prompt.updated_at.desc()],
        "recent": [Prompt.last_used_at.desc().nulls_last(), Prompt.updated_at.desc()],
        "popular": [Prompt.use_count.desc(), Prompt.updated_at.desc()],
        "rating": [func.coalesce(Prompt.rating, 0).desc(), Prompt.updated_at.desc()],
        "title": [func.lower(Prompt.title).asc()],
    }
    if sort == "relevance" and rank is not None:
        return [rank.asc(), Prompt.id]  # bm25(): lower (more negative) is better
    return [*by.get(sort, by["updated"]), Prompt.id]


# Column weights for bm25(): title, description, body, tags_text
_FTS_SQL = (
    "SELECT rowid AS rid, bm25(prompt_fts, 8.0, 3.0, 1.0, 4.0) AS rank "
    "FROM prompt_fts WHERE prompt_fts MATCH :q"
)


def _ranked_fast(session: Session, match: str, limit: int, offset: int) -> tuple[list[Prompt], int]:
    """Search-box fast path: no other filters, relevance order. The FTS index holds only live
    prompts, so rank + count come straight from it with no join (several times faster)."""
    params: dict[str, Any] = {"q": match}
    total = int(
        session.scalar(text("SELECT count(*) FROM prompt_fts WHERE prompt_fts MATCH :q"), params)
        or 0
    )
    if total == 0 or offset >= total:
        return [], total
    ids = session.scalars(
        text(
            "SELECT rowid FROM prompt_fts WHERE prompt_fts MATCH :q "
            "ORDER BY bm25(prompt_fts, 8.0, 3.0, 1.0, 4.0), rowid LIMIT :lim OFFSET :off"
        ),
        {**params, "lim": limit, "off": offset},
    ).all()
    rowid: Any = literal_column("prompt.rowid")
    found: dict[int, Prompt] = {
        rid: p
        for p, rid in session.execute(_load(select(Prompt, rowid).where(rowid.in_(ids)))).all()
    }
    return [found[i] for i in ids if i in found], total


def _run_query(
    session: Session,
    conds: list[Any],
    match: str | None,
    parsed: search_svc.ParsedQuery | None,
    sort: str,
    limit: int,
    offset: int,
    *,
    plain: bool = False,
    use_fts: bool = True,
) -> tuple[list[Prompt], int]:
    """`plain`: no filters beyond live/trash. `use_fts`: False forces the portable LIKE path."""
    sqlite = _is_sqlite(session) and use_fts
    if match and sqlite and plain and sort == "relevance":
        return _ranked_fast(session, match, limit, offset)
    rank: Any = None
    where = list(conds)
    join: tuple[Any, Any] | None = None
    if match and sqlite:
        fts = text(_FTS_SQL).bindparams(q=match).columns(rid=Integer, rank=Float).subquery("fts")
        join = (fts, literal_column("prompt.rowid") == fts.c.rid)
        rank = fts.c.rank
    elif parsed is not None and not parsed.empty:  # portable fallback (no FTS5)
        for tok in [*parsed.terms, *parsed.phrases]:
            like = f"%{tok}%"
            where.append(
                or_(
                    Prompt.title.ilike(like),
                    Prompt.description.ilike(like),
                    Prompt.body.ilike(like),
                    Prompt.tags_text.ilike(like),
                )
            )

    count_stmt = select(Prompt.id)
    page_stmt = _load(select(Prompt, rank) if rank is not None else select(Prompt))
    if join is not None:
        count_stmt = count_stmt.join(*join)
        page_stmt = page_stmt.join(*join)
    total = (
        session.scalar(select(func.count()).select_from(count_stmt.where(*where).subquery())) or 0
    )
    stmt = page_stmt.where(*where).order_by(*_order_by(sort, rank)).limit(limit).offset(offset)
    if rank is not None:
        rows = [r[0] for r in session.execute(stmt).all()]
    else:
        rows = list(session.scalars(stmt))
    return rows, total


def list_prompts(
    session: Session, f: ListFilters, limit: int = 50, cursor: str | None = None
) -> ListResult:
    """List/search prompts. `q` is full-text (BM25, prefix + stemming, "phrases"); if it finds
    nothing, near-miss words are corrected and the search is retried (`corrected_query`)."""
    if f.sort is not None and f.sort not in SORTS:
        raise ValidationFailed(f"sort must be one of: {', '.join(SORTS)}")
    parsed = search_svc.parse(f.q) if f.q else None
    if parsed is not None and parsed.empty:
        parsed = None
    match = search_svc.match_expression(parsed) if parsed else None
    sort = f.sort or ("relevance" if parsed else "updated")
    offset = _decode_cursor(cursor, sort) if cursor else 0
    conds = _filter_conditions(session, f)
    # The FTS index holds only live prompts, so searching the Trash uses the LIKE fallback.
    use_fts = not f.trash
    plain = len(conds) == 1  # only the live/trash condition
    run = {"plain": plain, "use_fts": use_fts}

    rows, total = _run_query(session, conds, match, parsed, sort, limit, offset, **run)
    corrected: str | None = None
    if total == 0 and parsed is not None and offset == 0 and _is_sqlite(session) and use_fts:
        fix = search_svc.suggest(session, parsed)
        if fix is not None:
            alternatives, corrected_text = fix
            match2 = search_svc.match_expression(parsed, alternatives)
            rows, total = _run_query(session, conds, match2, parsed, sort, limit, offset, **run)
            corrected = corrected_text if total else None

    nxt = _encode_cursor(sort, offset + limit) if offset + limit < total else None
    return ListResult(rows, total, nxt, sort, corrected)


def mark_used(session: Session, prompt: Prompt) -> Prompt:
    """Record a use (copy/run). Does not touch updated_at or the revision history."""
    session.execute(
        update(Prompt)
        .where(Prompt.id == prompt.id)
        .values(use_count=Prompt.use_count + 1, last_used_at=_now(), updated_at=Prompt.updated_at)
    )
    session.refresh(prompt)
    return prompt


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
            p.tags_text = tag_svc.tags_text(p.tags)
        elif action == "remove_tags":
            p.tags = [t for t in p.tags if t.name not in drop]
            p.tags_text = tag_svc.tags_text(p.tags)
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
