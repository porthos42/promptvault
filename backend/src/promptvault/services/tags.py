from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from promptvault.models import Prompt, Tag, prompt_tag
from promptvault.services.errors import NotFoundError, ValidationFailed

MAX_TAGS = 30


def normalize(name: str) -> str:
    return re.sub(r"\s+", "-", name.strip().lower())[:100]


def normalize_many(names: list[str]) -> list[str]:
    out: dict[str, None] = {}
    for n in names:
        norm = normalize(n)
        if norm:
            out.setdefault(norm, None)
    if len(out) > MAX_TAGS:
        raise ValidationFailed(f"At most {MAX_TAGS} tags per prompt")
    return list(out)


def tags_text(tags: list[Tag]) -> str:
    """Denormalised tag names, indexed by FTS."""
    return " ".join(sorted(t.name for t in tags))


def _reindex(session: Session, prompts: list[Prompt]) -> None:
    for p in prompts:
        session.refresh(p, ["tags"])
        p.tags_text = tags_text(p.tags)
    session.flush()


def get_or_create(session: Session, names: list[str]) -> list[Tag]:
    names = normalize_many(names)
    if not names:
        return []
    existing = {t.name: t for t in session.scalars(select(Tag).where(Tag.name.in_(names)))}
    for n in names:
        if n not in existing:
            existing[n] = Tag(name=n)
            session.add(existing[n])
    session.flush()
    return [existing[n] for n in names]


def list_tags(session: Session, include_unused: bool = False) -> list[tuple[str, int]]:
    live = (
        select(prompt_tag.c.tag_id, func.count().label("n"))
        .join(Prompt, Prompt.id == prompt_tag.c.prompt_id)
        .where(Prompt.deleted_at.is_(None))
        .group_by(prompt_tag.c.tag_id)
        .subquery()
    )
    rows = session.execute(
        select(Tag.name, func.coalesce(live.c.n, 0))
        .outerjoin(live, live.c.tag_id == Tag.id)
        .order_by(Tag.name)
    ).all()
    return [(n, int(c)) for n, c in rows if include_unused or c]


def _get(session: Session, name: str) -> Tag:
    tag = session.scalar(select(Tag).where(Tag.name == normalize(name)))
    if tag is None:
        raise NotFoundError(f"Tag '{name}' not found")
    return tag


def rename(session: Session, old: str, new: str) -> str:
    """Rename a tag; if `new` exists the two are merged."""
    tag, new_name = _get(session, old), normalize(new)
    if not new_name:
        raise ValidationFailed("Tag name cannot be empty")
    if new_name == tag.name:
        return new_name
    target = session.scalar(select(Tag).where(Tag.name == new_name))
    affected = list(session.scalars(select(Prompt).where(Prompt.tags.any(Tag.id == tag.id))))
    if target is None:
        tag.name = new_name
    else:
        for p in affected:
            p.tags = [t for t in p.tags if t.id != tag.id]
            if target not in p.tags:
                p.tags.append(target)
        session.flush()
        session.delete(tag)
    session.flush()
    _reindex(session, affected)
    return new_name


def delete(session: Session, name: str) -> None:
    tag = _get(session, name)
    affected = list(session.scalars(select(Prompt).where(Prompt.tags.any(Tag.id == tag.id))))
    session.delete(tag)
    session.flush()
    _reindex(session, affected)
