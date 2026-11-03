"""`promptvault import`: dry run, stdin, folders, duplicates, license gate, exit codes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from promptvault.cli import app
from promptvault.config import get_settings

runner = CliRunner()
DATA = Path(__file__).parent / "data" / "import"
CSV = "title,body,license\nFirst,Plan a trip to {{place}},MIT\nSecond,Write a haiku about {{topic}},MIT\n"


@pytest.fixture(autouse=True)
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PV_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def run(*args: str, input: str | None = None, code: int = 0) -> str:
    r = runner.invoke(app, list(args), input=input)
    assert r.exit_code == code, (args, r.exit_code, r.output)
    return r.output


def count() -> int:
    return int(json.loads(run("list", "--json", "--limit", "500"))["total"])


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    f = tmp_path / "prompts.csv"
    f.write_text(CSV, encoding="utf-8")
    return f


def test_dry_run_previews_and_writes_nothing(csv_file: Path) -> None:
    out = run("import", "csv", str(csv_file), "--dry-run")
    assert "2 row(s): 2 new, 0 duplicate, 0 invalid" in out
    assert count() == 0
    data = json.loads(run("import", "csv", str(csv_file), "--dry-run", "--json"))
    assert data["dry_run"] is True and data["new"] == 2 and data["rows"][0]["action"] == "create"
    assert count() == 0


def test_import_with_confirmation(csv_file: Path) -> None:
    out = run("import", "csv", str(csv_file), input="n\n", code=1)  # abort at the prompt
    assert "Import 2 prompt(s)?" in out and count() == 0
    out = run("import", "csv", str(csv_file), input="y\n")
    assert "Imported: 2 created" in out and count() == 2
    shown = json.loads(run("show", json.loads(run("list", "--json"))["items"][0]["id"], "--json"))
    assert shown["source"] == "import:csv" and shown["license"] == "MIT"


def test_duplicates_skip_replace_keep_both(csv_file: Path) -> None:
    run("import", "csv", str(csv_file), "--yes")
    again = run("import", "csv", str(csv_file), "--yes")
    assert "0 created" in again and "2 skipped" in again and count() == 2
    assert "2 duplicate" in run("import", "csv", str(csv_file), "--dry-run")
    assert "2 created" in run(
        "import", "csv", str(csv_file), "--yes", "--on-duplicate", "keep_both"
    )
    assert count() == 4
    out = run("import", "csv", str(csv_file), "--yes", "--on-duplicate", "replace")
    assert "2 replaced" in out and count() == 4
    run("import", "csv", str(csv_file), "--on-duplicate", "bogus", code=2)


def test_stdin_requires_yes_and_reads_clipboard_text() -> None:
    run("import", "clipboard", "-", input="Alpha body\n---\nBeta body\n", code=2)
    out = run(
        "import",
        "clipboard",
        "-",
        "--yes",
        "--confirm-license",
        input="Alpha body\n---\nBeta body\n",
    )
    assert "2 created" in out and count() == 2


def test_license_gate_flags_and_exit_codes(tmp_path: Path) -> None:
    f = tmp_path / "nolicense.csv"
    f.write_text("title,body\nOne,Body one about tea\n", encoding="utf-8")
    out = run("import", "csv", str(f), "--yes", code=1)
    assert "1 refused" in out and "--confirm-license" in out and count() == 0
    assert "1 created" in run("import", "csv", str(f), "--yes", "--license", "CC0-1.0")
    g = tmp_path / "second.csv"
    g.write_text("title,body\nTwo,Body two about coffee\n", encoding="utf-8")
    assert "1 created" in run("import", "csv", str(g), "--yes", "--confirm-license")
    bad = tmp_path / "bad.csv"
    bad.write_text("title,body,license\n,no title,MIT\n", encoding="utf-8")
    assert "1 invalid" in run("import", "csv", str(bad), "--yes", code=1)


def test_mapping_option_and_error_messages(tmp_path: Path) -> None:
    f = tmp_path / "odd.csv"
    f.write_text("name,stuff,license\nMapped,Do {{x}},MIT\n", encoding="utf-8")
    out = run("import", "csv", str(f), "--yes", code=1)
    assert "No column for: body" in out
    assert "1 created" in run("import", "csv", str(f), "--yes", "-m", "body=stuff")
    run("import", "csv", str(f), "-m", "nonsense", "--dry-run", code=2)
    out = run("import", "csv", str(tmp_path / "missing.csv"), "--dry-run", code=1)
    assert "not found" in out


def test_markdown_folder_and_zip(tmp_path: Path) -> None:
    out = run("import", "markdown", str(DATA / "md"), "--dry-run")
    assert "4 row(s)" in out and "invalid YAML" in out
    out = run("import", "markdown", str(DATA / "md"), "--yes", "--confirm-license")
    assert "3 created" in out and "1 invalid" in out
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "No .md" in run("import", "markdown", str(empty), "--dry-run", code=1)
    run("import", "csv", str(DATA), "--dry-run", code=1)  # a folder for a file importer


def test_xlsx_file(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Title", "Body", "License"])
    ws.append(["From Excel", "Summarize {{doc}}", "MIT"])
    path = tmp_path / "p.xlsx"
    wb.save(path)
    assert "1 created" in run("import", "xlsx", str(path), "--yes")
