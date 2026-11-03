"""`promptvault export` and `promptvault share`: stdout vs file, overwrite rules, exit codes."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from promptvault.cli import app
from promptvault.config import get_settings
from promptvault.services import export as export_svc

runner = CliRunner()


@pytest.fixture(autouse=True)
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PV_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def invoke(*args: str, code: int = 0) -> Any:
    r = runner.invoke(app, list(args))
    assert r.exit_code == code, (args, r.exit_code, r.output)
    return r


def add(title: str, body: str, *extra: str) -> str:
    out = invoke("add", "--title", title, "--body", body, "--json", *extra).output
    return str(json.loads(out)["id"])


@pytest.fixture
def library() -> dict[str, str]:
    invoke("category", "add", "Writing", "--slug", "writing")
    ids = {
        "alpha": add("Alpha", "alpha body {{x}}", "-c", "writing", "-t", "a", "-t", "shared"),
        "beta": add("Beta", "beta body words", "-t", "shared"),
        "gamma": add("Gamma", "gamma body text"),
    }
    invoke("edit", ids["beta"], "--favorite")
    return ids


def test_export_json_to_a_file(library: dict[str, str], tmp_path: Path) -> None:
    out = invoke("export", "json", "out.json").output
    assert "Exported 3 prompt(s) to out.json" in out
    doc = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert [p["title"] for p in doc["prompts"]] == ["Alpha", "Beta", "Gamma"]
    assert not (tmp_path / "out.json.part").exists()


def test_default_file_names(library: dict[str, str], tmp_path: Path) -> None:
    invoke("export", "csv")
    invoke("export", "markdown", "--zip")
    invoke("export", "markdown")
    names = {p.name for p in tmp_path.iterdir() if p.name.startswith("promptvault-export-")}
    assert {n.rsplit(".", 1)[-1] for n in names if "." in n} == {"csv", "zip"}
    folder = next(p for p in tmp_path.iterdir() if p.is_dir() and p.name.startswith("promptvault-"))
    assert (folder / "writing" / "alpha.md").is_file()


def test_stdout_for_json_and_csv_only(library: dict[str, str]) -> None:
    r = runner.invoke(app, ["export", "json", "-"])
    assert r.exit_code == 0
    assert json.loads(r.stdout_bytes.decode("utf-8"))["count"] == 3  # data only on stdout
    assert "Exported 3 prompt(s) to stdout" in r.stderr
    r = runner.invoke(app, ["export", "csv", "-"])
    assert not r.stdout_bytes.startswith(b"\xef\xbb\xbf")  # no BOM when piping
    rows = list(csv.DictReader(io.StringIO(r.stdout_bytes.decode("utf-8"), newline="")))
    assert [x["title"] for x in rows] == ["Alpha", "Beta", "Gamma"]
    for binary in ("xlsx", "markdown"):
        r = runner.invoke(app, ["export", binary, "-"])
        assert r.exit_code == 2 and "binary" in r.output
    assert runner.invoke(app, ["export", "json", "-", "--json"]).exit_code == 2


def test_overwrite_needs_force(library: dict[str, str], tmp_path: Path) -> None:
    (tmp_path / "x.json").write_text("keep me", encoding="utf-8")
    out = invoke("export", "json", "x.json", code=1).output
    assert "already exists" in out and (tmp_path / "x.json").read_text() == "keep me"
    invoke("export", "json", "x.json", "--force")
    assert json.loads((tmp_path / "x.json").read_text(encoding="utf-8"))["count"] == 3


def test_markdown_folder_rules(library: dict[str, str], tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    invoke("export", "markdown", "empty")  # an empty folder is fine
    assert (tmp_path / "empty" / "uncategorised" / "beta.md").is_file()
    out = invoke("export", "markdown", "empty", code=1).output  # now it is not empty
    assert "already exists" in out
    invoke("export", "markdown", "empty", "--force")
    (tmp_path / "afile").write_text("x", encoding="utf-8")
    assert "already exists" in invoke("export", "markdown", "afile", code=1).output
    assert "is a file" in invoke("export", "markdown", "afile", "--force", code=1).output


def test_zip_and_xlsx_files(library: dict[str, str], tmp_path: Path) -> None:
    invoke("export", "markdown", "p.zip", "--zip")
    z = zipfile.ZipFile(tmp_path / "p.zip")
    assert sorted(z.namelist()) == [
        "uncategorised/beta.md",
        "uncategorised/gamma.md",
        "writing/alpha.md",
    ]
    invoke("export", "csv", "p.zip", code=1)  # already exists
    invoke("export", "json", "p.json", "--zip", code=2)  # --zip is markdown only
    if importlib.util.find_spec("openpyxl"):
        invoke("export", "xlsx", "p.xlsx")
        import openpyxl

        wb = openpyxl.load_workbook(tmp_path / "p.xlsx")
        assert wb["Prompts"].max_row == 4


def test_filters_and_ids(library: dict[str, str], tmp_path: Path) -> None:
    def titles(*args: str) -> list[str]:
        invoke("export", "json", "f.json", "--force", *args)
        return [p["title"] for p in json.loads((tmp_path / "f.json").read_text("utf-8"))["prompts"]]

    assert titles("-c", "writing") == ["Alpha"]
    assert titles("-t", "shared") == ["Alpha", "Beta"]
    assert titles("-t", "shared", "-t", "a") == ["Alpha"]
    assert titles("--favorite") == ["Beta"]
    assert titles("-q", "gamma") == ["Gamma"]
    assert titles("--id", library["beta"][:8]) == ["Beta"]
    assert titles("--id", library["beta"], "--id", library["gamma"]) == ["Beta", "Gamma"]
    invoke("rm", library["gamma"])
    assert titles() == ["Alpha", "Beta"]
    assert titles("--include-trashed") == ["Alpha", "Beta", "Gamma"]
    out = invoke("export", "json", "f.json", "--force", "--id", library["gamma"], code=1).output
    assert "Skipped 1 prompt(s) in Trash" in out and "nothing to export" in out
    assert invoke("export", "json", "f.json", "--force", "--id", "zzzzzzzz", code=1)


def test_empty_selection_exits_1_and_writes_nothing(
    library: dict[str, str], tmp_path: Path
) -> None:
    out = invoke("export", "json", "none.json", "-q", "zebra-nothing", code=1).output
    assert "nothing to export" in out and not (tmp_path / "none.json").exists()
    r = runner.invoke(app, ["export", "json", "-", "-q", "zebra-nothing"])
    assert r.exit_code == 1 and r.stdout_bytes == b""


def test_json_summary_and_unknown_format(library: dict[str, str]) -> None:
    summary = json.loads(invoke("export", "csv", "s.csv", "--json").output)
    assert summary["count"] == 3 and summary["path"] == "s.csv" and summary["bytes"] > 0
    assert summary["format"] == "csv" and summary["warnings"] == []
    assert "Unknown export format" in invoke("export", "pdf", "x.pdf", code=1).output


def test_unavailable_xlsx_names_the_extra(
    library: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        "importlib.util.find_spec", lambda n, *a: None if n == "openpyxl" else real(n, *a)
    )
    assert "prompt-vault[xlsx]" in invoke("export", "xlsx", "x.xlsx", code=1).output


def test_failed_write_leaves_no_partial_file(
    library: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_run = export_svc.run

    def broken(*args: Any, **kwargs: Any) -> Any:
        result = real_run(*args, **kwargs)

        def chunks() -> Iterator[bytes]:
            yield next(result.chunks)
            raise RuntimeError("disk on fire")

        result.chunks = chunks()
        return result

    monkeypatch.setattr(export_svc, "run", broken)
    r = runner.invoke(app, ["export", "json", "broken.json"])
    assert r.exit_code != 0
    assert not (tmp_path / "broken.json").exists() and not (tmp_path / "broken.json.part").exists()


def test_formula_guard_flag(tmp_path: Path) -> None:
    add("=SUM(1)", "-starts with a dash")
    invoke("export", "csv", "g.csv")
    invoke("export", "csv", "r.csv", "--raw")
    guarded = list(csv.DictReader(io.StringIO((tmp_path / "g.csv").read_text("utf-8-sig"))))
    raw = list(csv.DictReader(io.StringIO((tmp_path / "r.csv").read_text("utf-8-sig"))))
    assert guarded[0]["title"] == "'=SUM(1)" and raw[0]["title"] == "=SUM(1)"
    invoke("export", "csv", "nb.csv", "--no-bom")
    assert not (tmp_path / "nb.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert (tmp_path / "g.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_share(library: dict[str, str]) -> None:
    out = invoke("share", library["alpha"][:8]).output
    assert out.startswith("### Alpha\n\n```text\nalpha body {{x}}\n```\n")
    assert "- `{{x}}`: X" in out
    out = invoke("share", library["alpha"], "-f", "text", "-v", "x=42").output
    assert out == "Alpha\n\nalpha body 42\n"
    assert (
        json.loads(invoke("share", library["alpha"], "--format", "json").output)["title"] == "Alpha"
    )
    assert "Unknown variable" in invoke("share", library["alpha"], "-v", "y=1", code=1).output
    assert "Unknown share format" in invoke("share", library["alpha"], "-f", "html", code=1).output
    invoke("share", library["alpha"], "-v", "novalue", code=1)
    invoke("rm", library["alpha"])
    assert "in Trash" in invoke("share", library["alpha"], code=1).output
    invoke("share", "does-not-exist", code=1)
