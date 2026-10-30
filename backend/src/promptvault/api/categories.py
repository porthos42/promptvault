from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from promptvault.api.deps import DB
from promptvault.models import Category
from promptvault.schemas import CategoryCreate, CategoryOut, CategoryPatch
from promptvault.services import categories as svc

router = APIRouter(tags=["categories"])


def _out(db: DB, cat: Category, count: int | None = None) -> CategoryOut:
    parent = db.scalar(select(Category.slug).where(Category.id == cat.parent_id))
    if count is None:
        count = next((n for c, n in svc.list_categories(db) if c.id == cat.id), 0)
    return CategoryOut(
        slug=cat.slug,
        name=cat.name,
        parent=parent,
        icon=cat.icon,
        sort_order=cat.sort_order,
        prompt_count=count,
    )


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: DB) -> list[CategoryOut]:
    slugs = {cid: slug for cid, slug in db.execute(select(Category.id, Category.slug)).all()}
    return [
        CategoryOut(
            slug=c.slug,
            name=c.name,
            parent=slugs.get(c.parent_id) if c.parent_id else None,
            icon=c.icon,
            sort_order=c.sort_order,
            prompt_count=n,
        )
        for c, n in svc.list_categories(db)
    ]


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryCreate, db: DB) -> CategoryOut:
    return _out(db, svc.create_category(db, body.model_dump()), 0)


@router.get("/categories/{slug}", response_model=CategoryOut)
def get_category(slug: str, db: DB) -> CategoryOut:
    return _out(db, svc.get_by_slug(db, slug))


@router.patch("/categories/{slug}", response_model=CategoryOut)
def update_category(slug: str, body: CategoryPatch, db: DB) -> CategoryOut:
    cat = svc.update_category(db, svc.get_by_slug(db, slug), body.model_dump(exclude_unset=True))
    return _out(db, cat)


@router.delete("/categories/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(slug: str, db: DB) -> Response:
    svc.delete_category(db, svc.get_by_slug(db, slug))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
