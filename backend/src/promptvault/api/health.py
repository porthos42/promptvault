from __future__ import annotations

import os

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
    out = {"version": __version__}
    revision = os.environ.get("PV_REVISION")  # set by the Docker build (git commit)
    if revision and revision != "unknown":
        out["revision"] = revision
    return out
