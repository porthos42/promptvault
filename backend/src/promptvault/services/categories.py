from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from promptvault.models import Category, Prompt
from promptvault.services.errors import ConflictError, NotFoundError, ValidationFailed


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:100]


def get_by_slug(session: Session, slug: str) -> Category:
    cat = session.scalar(select(Category).where(Category.slug == slug))
    if cat is None:
        raise NotFoundError(f"Category '{slug}' not found")
    return cat


def list_categories(session: Session) -> list[tuple[Category, int]]:
    """All categories with a count of live (non-trashed) prompts, tree-ordered flat list."""
    counts = dict(
        session.execute(
            select(Prompt.category_id, func.count())
            .where(Prompt.deleted_at.is_(None), Prompt.category_id.is_not(None))
            .group_by(Prompt.category_id)
        ).all()
    )
    cats = session.scalars(select(Category).order_by(Category.sort_order, Category.name)).all()
    return [(c, int(counts.get(c.id, 0))) for c in cats]


def descendant_ids(session: Session, root: Category) -> list[int]:
    """The category's own id plus all descendants."""
    children: dict[int | None, list[int]] = {}
    for cid, pid in session.execute(select(Category.id, Category.parent_id)).all():
        children.setdefault(pid, []).append(cid)
    out, stack = [], [root.id]
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(children.get(cur, []))
    return out


def create_category(session: Session, data: dict[str, Any]) -> Category:
    slug = slugify(data.get("slug") or data["name"])
    if not slug:
        raise ValidationFailed("Category needs a name or slug with letters or digits")
    if session.scalar(select(Category.id).where(Category.slug == slug)) is not None:
        raise ConflictError(f"Category '{slug}' already exists")
    parent = get_by_slug(session, data["parent"]) if data.get("parent") else None
    cat = Category(
        slug=slug,
        name=data["name"],
        parent_id=parent.id if parent else None,
        icon=data.get("icon"),
        sort_order=data.get("sort_order", 0),
    )
    session.add(cat)
    session.flush()
    return cat


def update_category(session: Session, cat: Category, data: dict[str, Any]) -> Category:
    if "name" in data and data["name"]:
        cat.name = data["name"]
    if "icon" in data:
        cat.icon = data["icon"]
    if "sort_order" in data and data["sort_order"] is not None:
        cat.sort_order = data["sort_order"]
    if "parent" in data:
        if data["parent"]:
            parent = get_by_slug(session, data["parent"])
            if parent.id in descendant_ids(session, cat):
                raise ValidationFailed("A category cannot be its own ancestor")
            cat.parent_id = parent.id
        else:
            cat.parent_id = None
    session.flush()
    return cat


def delete_category(session: Session, cat: Category) -> None:
    """Prompts and child categories are kept; they become uncategorised / top-level."""
    session.delete(cat)
    session.flush()
