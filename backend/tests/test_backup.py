"""Tests for `promptvault backup`: snapshot content, rotation and restore usability."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from promptvault.cli import app
from promptvault.config import Settings, get_settings
from promptvault.db import run_migrations
from promptvault.services import backup as backup_svc
from promptvault.services import prompts as svc

runner = CliRunner()


def _prompt(title: str, body: str) -> dict[str, Any]:
    return {"title": title, "body": body}


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """An isolated vault: data dir + backups dir, migrated, with two prompts."""
    s = Settings(
        data_dir=tmp_path / "data",
        backup_dir=tmp_path / "backups",
        _env_file=None,  # type: ignore[call-arg]
    )
    monkeypatch.setenv("PV_DATA_DIR", str(s.data_dir))
    monkeypatch.setenv("PV_BACKUP_DIR", str(s.backup_dir))
    get_settings.cache_clear()
    run_migrations(s.resolved_database_url)
    with _session(s) as session:
        svc.create_prompt(session, _prompt("Alpha prompt", "Body alpha {{who}}"))
        svc.create_prompt(session, _prompt("Beta prompt", "Body beta"))
        session.commit()
    return s


def _prompt_count(db_file: Path) -> int:
    con = sqlite3.connect(db_file)
    try:
        return int(
            con.execute("SELECT count(*) FROM prompt WHERE deleted_at IS NULL").fetchone()[0]
        )
    finally:
        con.close()


class TestBackupCommand:
    def test_backup_writes_snapshot_with_identical_content(self, vault: Settings) -> None:
        r = runner.invoke(app, ["backup"])
        assert r.exit_code == 0, r.output
        assert "Backup written" in r.output
        backups = sorted(vault.resolved_backup_dir.glob("promptvault-backup-*.db"))
        assert len(backups) == 1
        assert _prompt_count(backups[0]) == 2

    def test_backup_content_matches_live_library_after_more_changes(self, vault: Settings) -> None:
        # Take a backup, then change the library; the backup must hold the state at its time.
        r = runner.invoke(app, ["backup"])
        assert r.exit_code == 0, r.output
        first = sorted(vault.resolved_backup_dir.glob("promptvault-backup-*.db"))[0]
        with _session(vault) as session:
            svc.create_prompt(session, _prompt("Later prompt", "Later body"))
            session.commit()
        assert _prompt_count(first) == 2
        r = runner.invoke(app, ["backup"])
        assert r.exit_code == 0, r.output
        second = sorted(vault.resolved_backup_dir.glob("promptvault-backup-*.db"))[1]
        assert _prompt_count(second) == 3

    def test_backup_rotation_keeps_seven(self, vault: Settings) -> None:
        for _ in range(8):
            r = runner.invoke(app, ["backup"])
            assert r.exit_code == 0, r.output
        backups = sorted(vault.resolved_backup_dir.glob("promptvault-backup-*.db"))
        assert len(backups) == 7

    def test_backup_keep_flag_overrides_settings(self, vault: Settings) -> None:
        for _ in range(4):
            r = runner.invoke(app, ["backup", "--keep", "2"])
            assert r.exit_code == 0, r.output
        backups = sorted(vault.resolved_backup_dir.glob("promptvault-backup-*.db"))
        assert len(backups) == 2


def _session(s: Settings) -> Session:
    engine = create_engine(s.resolved_database_url)
    return sessionmaker(engine)()  # type: ignore[return-value]


class TestBackupService:
    def test_restore_roundtrip(self, vault: Settings) -> None:
        """The backup file is a usable database: opening it shows the snapshot's prompts."""
        r = runner.invoke(app, ["backup"])
        assert r.exit_code == 0, r.output
        (backup_file,) = sorted(vault.resolved_backup_dir.glob("promptvault-backup-*.db"))
        # Add and trash prompts after the snapshot; the backup must not see any of that.
        with _session(vault) as session:
            p = svc.create_prompt(session, _prompt("Extra", "extra body"))
            session.commit()
            svc.trash_prompt(session, p)
            session.commit()
        assert _prompt_count(backup_file) == 2  # the snapshot stays at its two live prompts

    def test_create_backup_is_sqlite_only(self, vault: Settings) -> None:
        """A non-SQLite session bind is refused with a clear error."""

        class _FakeDialect:
            name = "postgresql"

        class _FakeBind:
            dialect = _FakeDialect()

        class _FakeSession:
            def get_bind(self) -> Any:
                return _FakeBind()

        from promptvault.services.errors import DomainError

        with pytest.raises(DomainError):
            backup_svc.create_backup(_FakeSession(), vault.resolved_backup_dir, keep=7)  # type: ignore[arg-type]
