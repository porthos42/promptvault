from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from promptvault.services.seed import SeedLibrary, library_from_settings


def get_db(request: Request) -> Iterator[Session]:
    """One session per request; commit on success, roll back on error."""
    session: Session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_seed_library(request: Request) -> SeedLibrary | None:
    """The seed library on disk (None when the install ships without one)."""
    return library_from_settings(request.app.state.settings)


DB = Annotated[Session, Depends(get_db)]
Seeds = Annotated[SeedLibrary | None, Depends(get_seed_library)]
