"""Export service: selection, determinism, and each format on its own."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from tests.helpers import make
from tests.test_export_roundtrip import build_library

from promptvault.importers import tabular
from promptvault.services import export
from promptvault.services.errors import NotFoundError, PayloadTooLarge, ValidationFailed

FIXED = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)


def run(client: TestClient, fmt: str, sel: export.Selection | None = None, **opts: Any) -> Any:
    opener = client.app.state.session_factory  # type: ignore[attr-defined]
    with opener() as session:
        plan = export.prepare(session, sel or export.Selection())
    return export.run(opener, fmt, plan, export.Options(**opts))


def plan_ids(client: TestClient, sel: export.Selection, **kw: Any) -> list[str]:
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        return export.prepare(session, sel, **kw).ids


def titles(client: TestClient, sel: export.Selection) -> list[str]:
    ids = plan_ids(client, sel)
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        return [r["title"] for r in export.load_records(session, ids)]


# ---- selection -----------------------------------------------------------------------------


def test_selection_filters_ids_trash_and_order(client: TestClient) -> None:
    for slug, parent in (("top", None), ("sub", "top")):
        client.post("/api/v1/categories", json={"name": slug, "slug": slug, "parent": parent})
    a = make(client, title="alpha", body="aaa body one", category="top", tags=["x", "y"])
    make(client, title="Bravo", body="bbb body two", category="sub", tags=["x"], is_favorite=True)
    make(client, title="charlie", body="ccc body three", tags=["y"])
    gone = make(client, title="delta", body="ddd body four")
    client.delete(f"/api/v1/prompts/{gone['id']}")

    def sel(**kw: Any) -> export.Selection:
        inc = kw.pop("include_trashed", False)
        ids = kw.pop("ids", None)
        return export.Selection(export.svc.ListFilters(**kw), ids, inc)

    assert titles(client, sel()) == ["alpha", "Bravo", "charlie"]  # case-insensitive title order
    assert titles(client, sel(include_trashed=True)) == ["alpha", "Bravo", "charlie", "delta"]
    assert titles(client, sel(category="top")) == ["alpha", "Bravo"]  # children included
    assert titles(client, sel(category="sub")) == ["Bravo"]
    assert titles(client, sel(tags=["x", "y"])) == ["alpha"]
    assert titles(client, sel(tags=["x", "y"], tags_mode="any")) == ["alpha", "Bravo", "charlie"]
    assert titles(client, sel(favorite=True)) == ["Bravo"]
    assert titles(client, sel(q="ccc")) == ["charlie"]
    assert titles(client, sel(q="ddd")) == []
    assert titles(client, sel(q="ddd", include_trashed=True)) == ["delta"]
    assert titles(client, sel(ids=[a["id"]])) == ["alpha"]
    assert titles(client, sel(category="top", ids=[a["id"]])) == ["alpha"]
    assert titles(client, sel(q="no-such-word-anywhere")) == []
    with pytest.raises(NotFoundError):
        plan_ids(client, sel(category="nope-not-a-category"))


def test_missing_ids_and_empty_selection(client: TestClient) -> None:
    p = make(client, title="One", body="one body")
    gone = make(client, title="Two", body="two body")
    client.delete(f"/api/v1/prompts/{gone['id']}")
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        plan = export.prepare(session, export.Selection(ids=[p["id"], gone["id"], "nope"]))
    assert plan.ids == [p["id"]] and plan.missing == [gone["id"], "nope"]
    assert plan.filters == {"ids_requested": 3}
    assert run(client, "json", export.Selection(ids=["nope"])).count == 0


def test_row_cap_is_a_413(client: TestClient) -> None:
    for i in range(3):
        make(client, title=f"p{i}", body=f"body number {i} zebra")
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        assert len(export.prepare(session, export.Selection(), max_rows=3).ids) == 3
        with pytest.raises(PayloadTooLarge, match="PV_EXPORT_MAX_ROWS"):
            export.prepare(session, export.Selection(), max_rows=2)


def test_unknown_and_unavailable_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationFailed, match="Unknown export format"):
        export.get_format("pdf")
    assert export.get_format("MD").name == "markdown"
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    with pytest.raises(NotFoundError, match="promptvault\\[xlsx\\]"):
        export.get_format("xlsx")
    listed = {f["name"]: f for f in export.describe_formats()}
    assert listed["xlsx"]["available"] is False and "xlsx" in listed["xlsx"]["reason"]
    assert listed["json"]["available"] is True


# ---- determinism ---------------------------------------------------------------------------


def test_output_is_byte_identical_for_json_csv_and_zip(client: TestClient) -> None:
    build_library(client)

    def digest(fmt: str) -> str:
        return hashlib.sha256(run(client, fmt, now=FIXED).read()).hexdigest()

    for fmt in ("json", "csv", "markdown"):
        assert digest(fmt) == digest(fmt), fmt
    assert (
        run(client, "json", now=FIXED).read() != run(client, "json", pretty=True, now=FIXED).read()
    )


# ---- JSON ----------------------------------------------------------------------------------


def test_json_envelope_and_record_shape(client: TestClient) -> None:
    client.post("/api/v1/categories", json={"name": "Writing", "slug": "writing"})
    make(client, title="Héllo ✓", body="Say {{x}}", category="writing", tags=["b", "a"])
    for pretty in (False, True):
        raw = run(client, "json", pretty=pretty, now=FIXED).read()
        doc = __import__("json").loads(raw.decode("utf-8"))
        assert doc["format"] == "promptvault-export" and doc["version"] == 1
        assert doc["exported_at"] == "2026-11-02T12:00:00Z" and doc["count"] == 1
        assert doc["categories"] == [
            {"slug": "writing", "name": "Writing", "parent": None, "icon": None, "sort_order": 0}
        ]
        rec = doc["prompts"][0]
        assert rec["title"] == "Héllo ✓" and rec["category"] == {
            "slug": "writing",
            "name": "Writing",
        }
        assert rec["tags"] == ["a", "b"] and rec["version"] == 1 and rec["source"] == "user"
        assert rec["variables"][0]["name"] == "x" and rec["deleted_at"] is None
        assert ("é" in raw.decode("utf-8")) and b"\\u00e9" not in raw  # UTF-8, not ASCII escapes
    assert run(client, "json", pretty=True).read().endswith(b"\n  ]\n}\n")


def test_json_empty_selection_is_valid(client: TestClient) -> None:
    doc = __import__("json").loads(run(client, "json", pretty=True).read())
    assert doc["count"] == 0 and doc["prompts"] == []
    doc = __import__("json").loads(run(client, "json").read())
    assert doc["count"] == 0 and doc["prompts"] == []


def test_categories_come_parents_first(client: TestClient) -> None:
    client.post("/api/v1/categories", json={"name": "Z root", "slug": "z-root"})
    r = client.post(
        "/api/v1/categories", json={"name": "A child", "slug": "a-child", "parent": "z-root"}
    )
    assert r.status_code == 201
    doc = __import__("json").loads(run(client, "json").read())
    assert [c["slug"] for c in doc["categories"]] == ["z-root", "a-child"]


# ---- CSV -----------------------------------------------------------------------------------


def parse_csv(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline="")))


def test_csv_bom_crlf_quoting_and_header(client: TestClient) -> None:
    body = 'He said "hi", then\nleft; a | b'
    make(client, title='Comma, "quote"', body=body, tags=["t1", "t2"])
    data = run(client, "csv").read()
    assert data.startswith(b"\xef\xbb\xbf") and not run(client, "csv", bom=False).read().startswith(
        b"\xef\xbb\xbf"
    )
    assert data.count(b"\r\n") == 2  # header + one row; the newline inside the body stays LF
    rows = parse_csv(data)
    assert len(rows) == 1 and rows[0]["title"] == 'Comma, "quote"' and rows[0]["body"] == body
    assert rows[0]["tags"] == "t1, t2" and rows[0]["is_favorite"] == "false"
    header = next(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert header[:5] == ["title", "body", "description", "category", "tags"]


def test_csv_formula_guard_on_and_off(client: TestClient) -> None:
    make(client, title="=1+1", body="@SUM(A1) is not a prompt")
    make(client, title="+plus", body="-minus start")
    guarded = {r["title"]: r for r in parse_csv(run(client, "csv").read())}
    assert set(guarded) == {"'=1+1", "'+plus"}
    assert guarded["'=1+1"]["body"] == "'@SUM(A1) is not a prompt"
    raw = {r["title"]: r for r in parse_csv(run(client, "csv", raw=True).read())}
    assert set(raw) == {"=1+1", "+plus"} and raw["+plus"]["body"] == "-minus start"


def test_guard_cell_rules() -> None:
    for risky in ("=A1", "+1", "-1", "@x", "\tx", "\rx"):
        assert export.guard_cell(risky) == "'" + risky
    for fine in ("plain", "a=b", "'quoted", ""):
        assert export.guard_cell(fine) == fine


def test_importers_undo_only_the_guard() -> None:
    for risky in ("=A1", "+1", "-1", "@x", "\tx", "\rx"):
        assert tabular.unguard("'" + risky) == risky
        assert tabular.unguard(risky) == risky  # nothing to undo
    for other in ("'plain", "'", "x'=", 5, None):
        assert tabular.unguard(other) == other
    drafts = tabular.rows_to_drafts(["title", "body"], [["'=T", "'-b"], ["'quoted", "body"]])
    assert [(x.title, x.body) for x in drafts] == [("=T", "-b"), ("'quoted", "body")]


# ---- XLSX ----------------------------------------------------------------------------------


def test_xlsx_layout_and_values(client: TestClient) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    make(client, title="=SUM(A1)", body="=cmd|'/c calc'!A0", tags=["a"], is_favorite=True)
    out = run(client, "xlsx")
    assert out.warnings == []
    wb = openpyxl.load_workbook(io.BytesIO(out.read()))  # formulas visible: they must not exist
    assert wb.sheetnames == ["Prompts"]
    ws = wb["Prompts"]
    assert ws.freeze_panes == "A2"
    head = [c.value for c in ws[1]]
    assert head[:3] == ["title", "body", "description"] and ws["A1"].font.b is True
    assert ws["B2"].alignment.wrap_text is True
    title, body = ws["A2"], ws["B2"]
    assert title.data_type == "s" and title.value == "'=SUM(A1)"  # text, never a formula
    assert body.data_type == "s" and body.value == "'=cmd|'/c calc'!A0"
    row = dict(zip(head, [c.value for c in ws[2]], strict=True))
    assert row["is_favorite"] is True and row["use_count"] == 0 and row["tags"] == "a"
    raw = openpyxl.load_workbook(io.BytesIO(run(client, "xlsx", raw=True).read()))["Prompts"]
    assert raw["A2"].value == "=SUM(A1)" and raw["A2"].data_type == "s"  # still not a formula


def test_xlsx_cell_limit_and_control_characters(client: TestClient) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    make(client, title="Huge", body="x" * 40_000)
    make(client, title="Control", body="abc\x01def")
    out = run(client, "xlsx")
    assert len(out.warnings) == 2
    wb = openpyxl.load_workbook(io.BytesIO(out.read()))
    assert wb.sheetnames == ["Prompts", "Notes"]
    rows = {r[0].value: r for r in wb["Prompts"].iter_rows(min_row=2)}
    huge = rows["Huge"][1].value
    assert len(huge) <= export.XLSX_CELL_LIMIT and "truncated by Prompt Vault" in huge
    assert re.search(r"\[truncated by Prompt Vault: (\d+) more characters", huge)
    assert rows["Control"][1].value == "abcdef"
    notes = [[c.value for c in r] for r in wb["Notes"].iter_rows(min_row=3)]
    assert {n[1] for n in notes} == {"Huge", "Control"} and {n[2] for n in notes} == {"body"}


def test_fit_cell_boundaries() -> None:
    assert export._fit_cell("a" * export.XLSX_CELL_LIMIT) == ("a" * export.XLSX_CELL_LIMIT, 0)
    for n in (export.XLSX_CELL_LIMIT + 1, 100_000, 10_000_000):
        text, lost = export._fit_cell("a" * n)
        assert len(text) <= export.XLSX_CELL_LIMIT and lost > 0 and f"{lost} more" in text


# ---- Markdown ZIP --------------------------------------------------------------------------

SAFE_PATH = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*\.md$")


def zip_entries(client: TestClient) -> dict[str, str]:
    zf = zipfile.ZipFile(io.BytesIO(run(client, "markdown").read()))
    assert zf.testzip() is None
    return {i.filename: zf.read(i).decode("utf-8") for i in zf.infolist()}


def test_zip_names_are_safe_unique_and_deterministic(client: TestClient) -> None:
    client.post("/api/v1/categories", json={"name": "Odd / Name: ?*", "slug": "con"})
    client.post("/api/v1/categories", json={"name": "Deep", "slug": "x" * 100})
    for title, cat in (
        ("CON", "con"),
        ("con", "con"),
        ("Nul", None),
        ("COM1", None),
        ("../../etc/passwd", None),
        ("a\\b:c*d?e", None),
        ("日本語のみ", None),
        ("Same", None),
        ("same", None),
        ("T" * 300, "x" * 100),
        ("trailing dot.", None),
    ):
        make(client, title=title, body=f"unique body for {title!r}", category=cat)
    entries = zip_entries(client)
    names = list(entries)
    assert len(names) == 11 == len({n.lower() for n in names})
    for n in names:
        assert SAFE_PATH.match(n), n
        assert ".." not in n and "\\" not in n and ":" not in n and len(n) < 200
        assert n.split("/")[1].removesuffix(".md") not in export.RESERVED_NAMES
    assert "con-prompt/con-prompt.md" in names and "con-prompt/con-prompt-2.md" in names
    assert "uncategorised/nul-prompt.md" in names and "uncategorised/com1-prompt.md" in names
    assert "uncategorised/same.md" in names and "uncategorised/same-2.md" in names
    assert any(re.fullmatch(r"uncategorised/prompt-[0-9a-f]{8}\.md", n) for n in names)  # CJK
    zf = zipfile.ZipFile(io.BytesIO(run(client, "markdown").read()))
    assert {i.date_time for i in zf.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    assert {i.create_system for i in zf.infolist()} == {3}
    assert all(((i.external_attr >> 16) & 0o170000) == 0o100000 for i in zf.infolist())


def test_markdown_file_is_front_matter_plus_body(client: TestClient) -> None:
    client.post("/api/v1/categories", json={"name": "Writing", "slug": "writing"})
    make(
        client,
        title='Key: "value" # no comment',
        body="Body {{x}}\n\n---\nsecond part\n",
        description="line one\nline two",
        category="writing",
        tags=["b", "a"],
        license="MIT",
        disclaimer="Careful.",
        model_hints=None,
    )
    ((name, text),) = zip_entries(client).items()
    assert name == "writing/key-value-no-comment.md"
    assert text.startswith("---\n") and text.endswith("\n")
    front, body = text[4:].split("\n---\n\n", 1)
    meta = yaml.safe_load(front)
    assert meta == {
        "title": 'Key: "value" # no comment',
        "category": "writing",
        "tags": ["a", "b"],
        "difficulty": "beginner",
        "type": "template",
        "license": "MIT",
        "disclaimer": "Careful.",
        "description": "line one\nline two",
    }
    assert "description: |" in front  # multi-line text stays readable
    assert body.rstrip("\n") == "Body {{x}}\n\n---\nsecond part"
    assert "\r" not in text


def test_slug_helpers() -> None:
    assert export.slugify_name("Héllo Wörld!") == "hello-world"
    assert export.slugify_name("日本語") == ""
    assert export.safe_stem("aux", "x") == "aux-prompt" and export.safe_stem("", "fb") == "fb"
    assert len(export.safe_stem("a" * 200, "x")) == export.STEM_LIMIT
    used: set[str] = set()
    assert export.unique_path("d", "s", used) == "d/s.md"
    assert export.unique_path("d", "S", used) == "d/S-2.md"  # case-insensitive clash
    assert export.unique_path("e", "s", used) == "e/s.md"


# ---- share snippet -------------------------------------------------------------------------


def record(client: TestClient, **over: Any) -> dict[str, Any]:
    made = make(client, **over)
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        return export.load_records(session, [made["id"]])[0]


def test_share_markdown_text_and_json(client: TestClient) -> None:
    rec = record(
        client,
        title="Greeter",
        body="Say hi to {{name}} in {{lang}}.\n```\ncode\n````\n",
        description="A greeter.",
        license="MIT",
        source_url="https://example.org/g",
        disclaimer="Be nice.",
    )
    md, missing = export.share_snippet(rec, "markdown")
    assert missing == ["name", "lang"]
    assert md.startswith("### Greeter\n\nA greeter.\n\n`````text\nSay hi")  # fence beats ````
    assert "- `{{name}}`: Name" in md and "> Be nice." in md
    assert "_License: MIT | Source: https://example.org/g_" in md
    filled, missing = export.share_snippet(rec, "markdown", {"name": "Ada"})
    assert missing == ["lang"] and "Say hi to Ada in {{lang}}." in filled
    assert "{{name}}`" not in filled and "{{lang}}`" in filled
    done, missing = export.share_snippet(rec, "text", {"name": "Ada", "lang": "Welsh"})
    assert missing == [] and "Variables" not in done and done.startswith("Greeter\n\nSay hi to Ada")
    doc = __import__("json").loads(export.share_snippet(rec, "json")[0])
    assert doc["title"] == "Greeter" and [v["name"] for v in doc["variables"]] == ["name", "lang"]
    with pytest.raises(ValidationFailed, match="Unknown variable"):
        export.share_snippet(rec, "text", {"nme": "typo"})
    with pytest.raises(ValidationFailed, match="Unknown share format"):
        export.share_snippet(rec, "html")


def test_spool_is_closed_after_streaming(client: TestClient) -> None:
    make(client, title="x", body="some body")
    out = run(client, "markdown")
    spool = out.chunks.gi_frame.f_locals["spool"]
    out.read()
    assert spool.closed
