"""M3d headline test: export -> import into an EMPTY database -> export again.

The two exports must be equal once the things that are export-only metadata are removed: ids,
timestamps, personal state (favorite, rating, use count), version numbers and the source marker
(`user` vs `import:<format>`). The importer reads content and provenance only (SPEC 3.6), so
that is exactly what is compared. Every export format has to pass.

Two things are asserted as losses on purpose instead of being hidden:
* variable metadata (label, default, options) is rebuilt from the body on import;
* body, title and description are normalized on import like for every importer (LF endings, no
  trailing spaces, at most one blank line in a row, trimmed).
"""

from __future__ import annotations

import base64
import random
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from promptvault.config import Settings
from promptvault.importers.normalize import normalize_text
from promptvault.main import create_app

EXPORT = "/api/v1/export"
COMMIT = "/api/v1/import/commit"
FORMATS = ["json", "csv", "xlsx", "markdown"]
CONTENT_FIELDS = (
    "title",
    "body",
    "description",
    "category",
    "tags",
    "difficulty",
    "prompt_type",
    "model_hints",
    "output_format",
    "disclaimer",
    "license",
    "source_url",
)


def _client(path: Path) -> Iterator[TestClient]:
    path.mkdir(parents=True, exist_ok=True)
    with TestClient(create_app(Settings(data_dir=path, _env_file=None))) as c:  # type: ignore[call-arg]
        yield c


@pytest.fixture
def lib(tmp_path: Path) -> Iterator[TestClient]:
    """The library that gets exported."""
    yield from _client(tmp_path / "source")


@pytest.fixture
def empty(tmp_path: Path) -> Iterator[TestClient]:
    """A second, empty installation that the export is imported into."""
    yield from _client(tmp_path / "target")


# ---- the mixed library ---------------------------------------------------------------------


def specs() -> list[dict[str, Any]]:
    """Seed-like prompts plus the messy cases. Bodies are distinct random words, because similar
    bodies would be fuzzy duplicates of each other."""
    rng = random.Random(7)

    def words(n: int) -> str:
        return " ".join(f"w{rng.getrandbits(32):08x}" for _ in range(n))

    base: dict[str, Any] = {"license": "MIT", "category": "writing"}
    cases: list[dict[str, Any]] = [
        {
            "title": "Resume Bullet Rewriter",
            "body": "Rewrite {{bullet}} for {{job_title}}. " + words(10),
            "description": "Line one.\n\nLine two with *markdown*.",
            "category": "resumes",
            "tags": ["resume", "career"],
            "variables": [
                {"name": "bullet", "label": "Bullet text", "type": "textarea", "default": "Led"},
                {"name": "job_title", "type": "select", "options": ["PM", "Engineer"]},
            ],
            "difficulty": "intermediate",
            "model_hints": "gpt-4o, claude",
            "output_format": "markdown",
            "source_url": "https://example.org/resume",
            "is_favorite": True,
        },
        {
            "title": "R\u00e9sum\u00e9 \U0001f4bc \u2013 na\u00efve caf\u00e9 \u65e5\u672c\u8a9e",
            "body": "\u00c9cris un r\u00e9sum\u00e9 \U0001f4bc pour {{nom}} \u2014 \u2713 "
            + words(8),
        },
        {
            "title": "CRLF and trailing spaces",
            "body": "Line one  \r\nLine two\r\n\r\n\r\n\r\nLine three\t \r\n" + words(6),
        },
        {"title": "Very long body", "body": words(2000)},
        {
            "title": "Stray braces",
            "body": "Stray {{ brace and }} and {{ok}} and {{ spaced }} " + words(6),
        },
        {
            "title": "Many tags, no category",
            "body": words(9),
            "category": None,
            "tags": [f"tag-{i}" for i in range(12)],
        },
        {
            "title": "Full metadata",
            "body": "Act as {{role}}. " + words(7),
            "description": "Everything set.",
            "tags": ["system", "meta"],
            "difficulty": "advanced",
            "prompt_type": "system",
            "model_hints": "any model",
            "output_format": "json",
            "disclaimer": "Not legal advice.",
            "license": "CC-BY-4.0",
            "source_url": "https://example.org/full",
        },
        {"title": "No license at all", "body": words(9), "license": None},
        # spreadsheet formula guard: every one of these must come back unchanged
        {"title": "=SUM(A1) title", "body": "- first item\n- second item " + words(5)},
        {"title": "+1 plus title", "body": "=cmd|'/c calc'!A0 " + words(5)},
        {"title": "@mention title", "body": "@user please " + words(5)},
        {"title": "-dash title", "body": "\tindented start " + words(5)},
        {
            "title": "CSV hostile",
            "body": 'He said "hi", then left;\nsecond line, with | pipe\n\n---\n# Heading in body\n'
            + words(5),
        },
        # YAML hostile titles for the Markdown front-matter
        {"title": 'Key: "value" # not a comment', "body": words(8)},
        {"title": "yes", "body": words(8)},
        {"title": "2024", "body": words(8)},
        # file names: Windows reserved names, a name that cannot be slugified, same title twice
        {"title": "CON", "body": words(8)},
        {"title": "con", "body": words(8)},
        {"title": "\u65e5\u672c\u8a9e\u306e\u307f", "body": words(8)},
        {"title": "Same Title", "body": words(8)},
        {"title": "Same Title", "body": words(8)},
    ]
    assert len(cases) <= 25  # commits above 25 rows become background jobs
    return [{**base, **c} for c in cases]


def build_library(client: TestClient) -> None:
    for slug, name, parent in (("writing", "Writing", None), ("resumes", "Resumes", "writing")):
        r = client.post("/api/v1/categories", json={"slug": slug, "name": name, "parent": parent})
        assert r.status_code == 201, r.text
    for spec in specs():
        r = client.post("/api/v1/prompts", json=spec)
        assert r.status_code == 201, r.text
    first = client.get("/api/v1/prompts", params={"q": "Resume Bullet"}).json()["items"][0]
    client.patch(f"/api/v1/prompts/{first['id']}", json={"rating": 5})
    client.post(f"/api/v1/prompts/{first['id']}/use")
    gone = client.post("/api/v1/prompts", json={"title": "Trashed", "body": "to be trashed"}).json()
    client.delete(f"/api/v1/prompts/{gone['id']}")


# ---- helpers -------------------------------------------------------------------------------


def export(client: TestClient, fmt: str, **params: Any) -> bytes:
    r = client.get(EXPORT, params={"format": fmt, **params})
    assert r.status_code == 200, r.text
    return r.content


def export_json(client: TestClient) -> dict[str, Any]:
    out: dict[str, Any] = client.get(EXPORT, params={"format": "json"}).json()
    return out


def opt(value: str | None) -> str | None:
    return (value or "").strip() or None


def expected_content(rec: dict[str, Any]) -> dict[str, Any]:
    """What the importer should make of an exported record: its normalization, nothing else."""
    return {
        "title": " ".join(rec["title"].split()),
        "body": normalize_text(rec["body"]),
        "description": normalize_text(rec["description"]),
        "category": rec["category"]["slug"] if rec["category"] else None,
        "tags": sorted(rec["tags"]),
        "difficulty": rec["difficulty"],
        "prompt_type": rec["prompt_type"],
        "model_hints": opt(rec["model_hints"]),
        "output_format": opt(rec["output_format"]),
        "disclaimer": opt(rec["disclaimer"]),
        "license": opt(rec["license"]),
        "source_url": opt(rec["source_url"]),
    }


def project(records: list[dict[str, Any]], *, expected: bool = False) -> list[dict[str, Any]]:
    rows = [expected_content(r) for r in records]
    return sorted(rows, key=lambda r: (r["title"], r["body"]))


def clone_categories(src: dict[str, Any], dest: TestClient) -> None:
    """Imports never create categories, so the empty target gets the exported ones first."""
    for c in src["categories"]:
        body = {k: c[k] for k in ("slug", "name", "parent", "icon", "sort_order")}
        assert dest.post("/api/v1/categories", json=body).status_code == 201


def reimport(client: TestClient, fmt: str, data: bytes) -> dict[str, Any]:
    if fmt in ("xlsx", "markdown"):
        source: Any = {"content_base64": base64.b64encode(data).decode("ascii")}
    else:
        source = {"content": data.decode("utf-8-sig")}
    r = client.post(
        COMMIT,
        json={
            "importer": fmt,
            "source": source,
            "default_action": "keep_both",  # a restore must not skip near-duplicates
            "confirm_license": True,  # nor refuse prompts that have no license
        },
    )
    assert r.status_code == 200, r.text
    job: dict[str, Any] = r.json()
    assert job["invalid"] == 0 and job["refused"] == 0 and job["skipped"] == 0, job
    return job


# ---- the tests -----------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_round_trip_export_import_export(lib: TestClient, empty: TestClient, fmt: str) -> None:
    if fmt == "xlsx":
        pytest.importorskip("openpyxl")
    build_library(lib)
    first = export_json(lib)
    assert first["count"] == len(specs()) == len(first["prompts"])  # trash is not exported

    clone_categories(first, empty)
    job = reimport(empty, fmt, export(lib, fmt))
    assert job["created"] == len(specs())

    second = export_json(empty)
    assert second["count"] == first["count"]
    assert project(second["prompts"]) == project(first["prompts"])
    # the same prompts are really there: nothing was merged, dropped or reordered into place
    assert {r["title"] for r in second["prompts"]} == {r["title"] for r in first["prompts"]}


@pytest.mark.parametrize("fmt", FORMATS)
def test_what_a_round_trip_does_not_restore(lib: TestClient, empty: TestClient, fmt: str) -> None:
    if fmt == "xlsx":
        pytest.importorskip("openpyxl")
    build_library(lib)
    first = export_json(lib)
    clone_categories(first, empty)
    reimport(empty, fmt, export(lib, fmt))
    second = export_json(empty)

    def by_title(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {r["title"]: r for r in doc["prompts"] if r["title"] != "Same Title"}

    a, b = by_title(first), by_title(second)
    title = "Resume Bullet Rewriter"
    # ids, personal state and the source marker are export-only
    assert (
        a[title]["is_favorite"] is True and a[title]["rating"] == 5 and a[title]["use_count"] == 1
    )
    assert b[title]["is_favorite"] is False and b[title]["rating"] is None
    assert b[title]["use_count"] == 0 and b[title]["last_used_at"] is None
    assert a[title]["id"] != b[title]["id"] and a[title]["source"] == "user"
    assert b[title]["source"] == f"import:{fmt}"
    # variable names survive (they come from the body); label, type, default and options do not
    assert [v["name"] for v in b[title]["variables"]] == [v["name"] for v in a[title]["variables"]]
    assert a[title]["variables"][0]["label"] == "Bullet text"
    assert b[title]["variables"][0]["label"] == "Bullet"
    assert a[title]["variables"][1]["options"] == ["PM", "Engineer"]
    assert b[title]["variables"][1]["options"] == []
