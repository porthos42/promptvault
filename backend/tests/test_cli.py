from pathlib import Path

from typer.testing import CliRunner

from promptvault.cli import app
from promptvault.config import get_settings

runner = CliRunner()


def test_version() -> None:
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert r.stdout.strip()


def test_init_and_doctor(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PV_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        r = runner.invoke(app, ["init"])
        assert r.exit_code == 0, r.stdout
        assert (tmp_path / "promptvault.db").exists()
        r = runner.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.stdout
        assert "FTS5" in r.stdout
    finally:
        get_settings.cache_clear()
