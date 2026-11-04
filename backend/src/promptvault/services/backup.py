"""SQLite library backup: a timestamped VACUUM INTO copy plus keep-N rotation."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from promptvault.services.errors import DomainError

log = logging.getLogger(__name__)

PREFIX = "promptvault-backup-"
SUFFIX = ".db"


def _stamp() -> str:
    # Microseconds keep two backups in the same second from overwriting each other,
    # and keep lexical name order equal to chronological order for rotation.
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")


def create_backup(session: Session, backup_dir: Path, *, keep: int = 7) -> Path:
    """Write a consistent snapshot of the whole library into `backup_dir`.

    SQLite's `VACUUM INTO` produces a compact, fully committed copy of the database
    (WAL included is not needed: it reads a consistent snapshot through the connection).
    Returns the path of the written file and rotates older backups (keep = number of
    `promptvault-backup-*.db` files kept, including the new one).
    """
    bind = session.get_bind()
    if bind.dialect.name != "sqlite":
        raise DomainError(
            "promptvault backup is SQLite-only (the configured database is not SQLite)"
        )
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{PREFIX}{_stamp()}{SUFFIX}"
    conn = session.connection()
    conn.exec_driver_sql("VACUUM INTO ?", (str(target),))
    if not target.is_file() or target.stat().st_size == 0:
        raise DomainError("backup file was not written")
    pruned = rotate_backups(backup_dir, keep=keep)
    if pruned:
        log.info("Pruned %d old backup(s)", pruned)
    return target


def rotate_backups(backup_dir: Path, *, keep: int) -> int:
    """Keep the newest `keep` backup files; delete the rest. Returns the number deleted."""
    if keep < 1:
        keep = 1
    files = sorted(backup_dir.glob(f"{PREFIX}*{SUFFIX}"), key=lambda p: p.name)
    removed = 0
    for old in files[:-keep] if len(files) > keep else []:
        try:
            old.unlink()
            removed += 1
        except OSError:
            log.warning("Could not delete old backup %s", old)
    return removed


def restore_instructions() -> str:
    """How to restore a backup file (kept here so docs and the CLI hint agree)."""
    return (
        "To restore: stop the server, move the current database file aside "
        "(<data_dir>/promptvault.db plus any -wal/-shm files), copy the chosen "
        "promptvault-backup-*.db over <data_dir>/promptvault.db, then start the server "
        "(migrations run automatically; the backup is always at or older than the live "
        "schema, so upgrading is a no-op or a forward migration)."
    )
