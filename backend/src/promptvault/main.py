"""FastAPI application factory. Serves the built React app when present."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from promptvault import __version__
from promptvault.api import categories, errors, health, prompts, tags
from promptvault.config import Settings, get_settings
from promptvault.db import make_engine, make_session_factory, run_migrations
from promptvault.services.prompts import purge_trash

log = logging.getLogger("promptvault")
STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.resolved_database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.auto_migrate:
            run_migrations(settings.resolved_database_url)
        if settings.trash_retention_days >= 0:
            with app.state.session_factory() as session:
                purged = purge_trash(session, settings.trash_retention_days)
                session.commit()
            if purged:
                log.info("Purged %d trashed prompts", purged)
        yield
        engine.dispose()

    app = FastAPI(title="Prompt Vault", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    errors.install(app)
    for r in (health.router, prompts.router, categories.router, tags.router):
        app.include_router(r, prefix="/api/v1")

    index = STATIC_DIR / "index.html"
    if index.is_file():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (STATIC_DIR / path).resolve()
            if candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index)

    return app


def app_factory() -> FastAPI:
    """Uvicorn factory entry point: `uvicorn promptvault.main:app_factory --factory`."""
    return create_app()
