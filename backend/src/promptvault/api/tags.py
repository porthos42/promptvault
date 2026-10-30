from __future__ import annotations

from fastapi import APIRouter, Response, status

from promptvault.api.deps import DB
from promptvault.schemas import TagOut, TagRename
from promptvault.services import tags as svc

router = APIRouter(tags=["tags"])


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: DB, include_unused: bool = False) -> list[TagOut]:
    return [TagOut(name=n, prompt_count=c) for n, c in svc.list_tags(db, include_unused)]


@router.put("/tags/{name}", response_model=TagOut)
def rename_tag(name: str, body: TagRename, db: DB) -> TagOut:
    """Rename a tag. If the new name already exists, the tags are merged."""
    new = svc.rename(db, name, body.name)
    count = dict(svc.list_tags(db, include_unused=True)).get(new, 0)
    return TagOut(name=new, prompt_count=count)


@router.delete("/tags/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(name: str, db: DB) -> Response:
    svc.delete(db, name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
