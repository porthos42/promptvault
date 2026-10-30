import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from promptvault.cli import app
from promptvault.config import get_settings

runner = CliRunner()


@pytest.fixture(autouse=True)
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PV_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def run(*args: str) -> str:
    r = runner.invoke(app, list(args))
    assert r.exit_code == 0, (args, r.output)
    return r.output


def test_full_lifecycle() -> None:
    run("category", "add", "Resume Writing")
    out = run(
        "add",
        "--title",
        "Bullet Rewriter",
        "--body",
        "Fix {{bullet}}",
        "-c",
        "resume-writing",
        "-t",
        "resume",
        "-t",
        "ats",
        "--json",
    )
    data = json.loads(out)
    pid = data["id"]
    assert data["category"] == "resume-writing" and data["tags"] == ["ats", "resume"]
    assert [v["name"] for v in data["variables"]] == ["bullet"]

    assert "Bullet Rewriter" in run("list")
    assert json.loads(run("list", "--json", "-t", "ats"))["total"] == 1
    assert json.loads(run("list", "--json", "-t", "nope"))["total"] == 0

    shown = json.loads(run("show", pid[:6], "--json"))  # unique prefix works
    assert shown["version"] == 1 and shown["body"] == "Fix {{bullet}}"

    run("edit", pid[:6], "--title", "Better Rewriter", "--no-favorite", "--tag", "career")
    shown = json.loads(run("show", pid, "--json"))
    assert shown["title"] == "Better Rewriter" and shown["tags"] == ["career"]
    assert shown["version"] == 2

    out = run("rm", pid)
    assert "Trash" in out
    assert "(0 of 0)" in run("list")
    assert "Better Rewriter" in run("trash", "list")
    run("restore", pid)
    assert "(1 of 1)" in run("list")

    assert runner.invoke(app, ["rm", pid, "--permanent"]).exit_code == 1  # not trashed
    run("rm", pid)
    run("rm", pid, "--permanent")
    assert runner.invoke(app, ["show", pid]).exit_code == 1


def test_errors_and_tags_categories() -> None:
    r = runner.invoke(app, ["add", "--title", "x", "--body", "y", "-c", "missing"])
    assert r.exit_code == 1 and "not found" in r.output.lower()
    r = runner.invoke(app, ["add", "--title", "x", "--body", "y", "--difficulty", "expert"])
    assert r.exit_code == 2
    run("add", "--title", "A", "--body", "b", "-t", "x")
    assert "x" in run("tag", "list")
    run("tag", "rename", "x", "y")
    assert "y" in run("tag", "list")
    run("category", "add", "Coding")
    assert "coding" in run("category", "list")
    run("category", "rm", "coding")
    assert "Purged 0" in run("trash", "purge")
