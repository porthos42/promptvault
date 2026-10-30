from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from promptvault import __version__

router = APIRouter(tags=["ops"])


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    """Liveness + DB reachability."""
    with request.app.state.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/version")
def version() -> dict[str, str]:
    return {"version": __version__}
