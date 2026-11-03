"""Concrete importers: golden files, mapping, encodings, ZIP safety, clipboard, XLSX."""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from promptvault import importers
from promptvault.importers import clipboard, local, sources, tabular
from promptvault.importers.base import PromptDraft
from promptvault.importers.csv_import import detect_delimiter
from promptvault.importers.markdown_import import parse_file
from promptvault.services.errors import NotFoundError, PayloadTooLarge, ValidationFailed

DATA = Path(__file__).parent / "data" / "import"
HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None


def b64(data: bytes) -> dict[str, str]:
    return {"content_base64": base64.b64encode(data).decode("ascii")}


def parse(name: str, source: Any) -> list[PromptDraft]:
    return importers.get(name).parse(source)


def zip_bytes(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def slim(d: PromptDraft) -> dict[str, Any]:
    out = {
        k: v for k, v in d.to_dict().items() if v not in ("", [], None) or k in ("title", "body")
    }
    out["errors"] = [
        e.split(" (")[0] if e.startswith("front-matter: invalid YAML") else e for e in d.errors
    ]
    if not out["errors"]:
        del out["errors"]
    return out


# ---- golden files ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "importer", "path"),
    [
        ("json", "json", DATA / "prompts.json"),
        ("messy_csv", "csv", DATA / "messy.csv"),
        ("clean_csv", "csv", DATA / "clean.csv"),
        ("markdown_folder", "markdown", DATA / "md"),
    ],
)
def test_golden_files(key: str, importer: str, path: Path) -> None:
    expected = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))[key]
    for e in expected:
        e["errors"] = [x.split(" (")[0] for x in e.get("errors", [])] or None
        if e["errors"] is None:
            del e["errors"]
    got = [slim(d) for d in parse(importer, local.build_source(importer, str(path)))]
    assert got == expected


def test_registry_lists_importers_and_xlsx_availability() -> None:
    names = {i["name"]: i for i in importers.registry.describe()}
    assert {"json", "csv", "markdown", "clipboard", "passthrough"} <= set(names)
    assert names["xlsx"]["available"] is bool(HAS_OPENPYXL)
    assert all(i["description"] for n, i in names.items() if n != "passthrough")


def test_unavailable_importer_explains_itself() -> None:
    reg = importers.ImporterRegistry()
    reg.mark_unavailable("xlsx", "Excel", "install the extra")
    assert reg.describe() == [
        {"name": "xlsx", "description": "Excel", "available": False, "reason": "install the extra"}
    ]
    with pytest.raises(NotFoundError, match="install the extra"):
        reg.get("xlsx")


# ---- mapping and aliases -----------------------------------------------------------------


def test_aliases_and_explicit_mapping() -> None:
    headers = ["Prompt Name", "Text", "Labels", "Link", "Who"]
    cols, ignored = tabular.resolve_columns(headers)
    assert cols == {"title": 0, "body": 1, "tags": 2, "source_url": 3}
    assert ignored == ["Who"]
    cols, _ = tabular.resolve_columns(["a", "b", "c"], {"title": "c", "body": "A"})
    assert cols == {"title": 2, "body": 0}
    with pytest.raises(ValidationFailed, match="column 'zzz' not found"):
        tabular.resolve_columns(["a"], {"title": "zzz"})
    with pytest.raises(ValidationFailed, match="unknown field"):
        tabular.resolve_columns(["a"], {"nope": "a"})


def test_csv_mapping_override_and_missing_columns() -> None:
    text = "name,stuff,notes\nHello,Say hi to {{who}},x\n"
    with pytest.raises(ValidationFailed, match="No column for: body"):
        parse("csv", text)
    drafts = parse("csv", {"content": text, "mapping": {"body": "stuff"}})
    assert (drafts[0].title, drafts[0].body) == ("Hello", "Say hi to {{who}}")
    assert any("body<-stuff" in w for w in drafts[0].warnings)
    assert any("ignored: notes" in w for w in drafts[0].warnings)


def test_json_mapping_and_forms() -> None:
    rows = [{"n": "A", "t": "body a", "labels": "x; y|z"}]
    drafts = parse("json", {"prompts": rows, "mapping": {"title": "n", "body": "t"}})
    assert drafts[0].tags == ["x", "y", "z"]
    assert parse("json", json.dumps(rows[:0] + [{"title": "T", "body": "B"}]))[0].title == "T"
    assert parse("json", {"title": "Single", "body": "one"})[0].title == "Single"
    assert parse("json", {"content": '[{"title":"C","body":"b"}]'})[0].title == "C"
    with pytest.raises(ValidationFailed, match="Invalid JSON"):
        parse("json", {"content": "{nope"})
    with pytest.raises(ValidationFailed, match="list of prompts"):
        parse("json", 42)


def test_tag_splitting_and_cell_coercion() -> None:
    assert tabular.coerce_tags("a, b;c|d,, ") == ["a", "b", "c", "d"]
    assert tabular.coerce_tags(["x ", None, " "]) == ["x"]
    assert tabular.coerce_text(3.0) == "3" and tabular.coerce_text(2.5) == "2.5"
    assert tabular.coerce_text(True) == "true" and tabular.coerce_text(None) is None


# ---- CSV ---------------------------------------------------------------------------------


def test_csv_delimiters_bom_crlf_and_quoted_newlines() -> None:
    for delim in (",", ";", "\t", "|"):
        text = f'title{delim}body\r\nA{delim}"line 1\r\nline 2"\r\nB{delim}plain\r\n'
        drafts = parse(
            "csv", {"content_base64": base64.b64encode(b"\xef\xbb\xbf" + text.encode()).decode()}
        )
        assert [d.title for d in drafts] == ["A", "B"], delim
        assert "line 2" in drafts[0].body
    assert detect_delimiter("a;b;c\n1,2,3") == ";"
    assert detect_delimiter("single") == ","
    assert [d.title for d in parse("csv", {"content": "title#body\nX#y\n", "delimiter": "#"})] == [
        "X"
    ]
    assert parse("csv", {"content": "title\tbody\nX\ty\n", "delimiter": "tab"})[0].body == "y"
    with pytest.raises(ValidationFailed, match="single character"):
        parse("csv", {"content": "a,b", "delimiter": "ab"})


def test_csv_errors() -> None:
    with pytest.raises(ValidationFailed, match="empty"):
        parse("csv", "\n\n")
    with pytest.raises(ValidationFailed, match="UTF-8"):
        parse("csv", {"content_base64": base64.b64encode(b"title,body\n\xff\xfe\xfa,x").decode()})
    with pytest.raises(ValidationFailed, match="base64"):
        parse("csv", {"content_base64": "not base64!!"})
    with pytest.raises(ValidationFailed, match="content"):
        parse("csv", {"nothing": 1})


def test_utf16_with_bom_is_read() -> None:
    data = "title,body\nÜber,Grüße {{x}}\n".encode("utf-16")
    drafts = parse("csv", b64(data))
    assert (drafts[0].title, drafts[0].body) == ("Über", "Grüße {{x}}")


# ---- Markdown ----------------------------------------------------------------------------


def test_front_matter_edge_cases() -> None:
    d = parse_file("x/my-note_file.md", "---\n---\nJust a body\n")
    assert (d.title, d.body, d.errors) == ("my note file", "Just a body", [])
    d = parse_file("a.md", "---\ntitle: T\ntags: a, b\ntext: ignored\n---\nBody")
    assert (d.title, d.tags, d.body) == ("T", ["a", "b"], "Body")  # `text` is not the body here
    d = parse_file("a.md", "---\n- a list\n---\nB")
    assert d.errors and "mapping" in d.errors[0] and d.body == "B"
    d = parse_file("a.md", "no front matter\n---\nrule below stays")
    assert d.body.endswith("rule below stays") and d.title == "a"
    d = parse_file("a.md", "---\r\ntitle: Win\r\n---\r\n# H\r\nBody\r\n")
    assert (d.title, d.body) == ("Win", "# H\nBody".replace("\n", "\r\n"))
    d = parse_file("a.md", "# Only heading\n")
    assert (d.title, d.body) == ("Only heading", "")  # empty body is caught by validation


def test_markdown_sources_zip_list_and_single() -> None:
    data = zip_bytes(
        {
            "pack/b.md": "---\ntitle: Bee\n---\nB body",
            "pack/a.md": "A body",
            "pack/.hidden.md": "skip",
            "__MACOSX/pack/a.md": "skip",
            "pack/image.png": b"\x89PNG",
            "pack/dir/": "",
            "pack/notes.txt": "T body",
        }
    )
    drafts = parse("markdown", b64(data))
    assert [(d.title, d.body) for d in drafts] == [
        ("a", "A body"),
        ("Bee", "B body"),
        ("notes", "T body"),
    ]
    files = {"files": [{"name": "x.md", "content": "X"}, {"name": "y.md", "content": "Y"}]}
    assert [d.title for d in parse("markdown", files)] == ["x", "y"]
    assert parse("markdown", "plain text")[0].body == "plain text"
    assert parse("markdown", {"content": "c", "name": "named.md"})[0].title == "named"
    with pytest.raises(ValidationFailed, match="list of"):
        parse("markdown", {"files": [{"name": 1}]})
    bad = zip_bytes({"ok.md": "fine", "bad.md": b"\x80\x81\x82"})
    drafts = parse("markdown", b64(bad))
    assert [d.title for d in drafts] == ["bad", "ok"] and "UTF-8" in drafts[0].errors[0]


def test_zip_safety() -> None:
    with pytest.raises(ValidationFailed, match="Unsafe path"):
        parse("markdown", b64(zip_bytes({"../evil.md": "x"})))
    with pytest.raises(ValidationFailed, match="Unsafe path"):
        parse("markdown", b64(zip_bytes({"/abs.md": "x"})))
    with pytest.raises(ValidationFailed, match="not a valid ZIP"):
        sources.open_zip(b"PK\x03\x04 broken")
    big = zip_bytes({"big.md": "a" * (sources.ZIP_MAX_MEMBER_BYTES + 1)})
    with pytest.raises(PayloadTooLarge, match="larger than"):
        parse("markdown", b64(big))


def test_zip_limits_on_entry_count_and_expanded_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "ZIP_MAX_ENTRIES", 3)
    with pytest.raises(PayloadTooLarge, match="entries"):
        sources.open_zip(zip_bytes({f"{i}.md": "x" for i in range(4)}))
    monkeypatch.setattr(sources, "ZIP_MAX_TOTAL_BYTES", 100)
    with pytest.raises(PayloadTooLarge, match="expands"):
        sources.open_zip(zip_bytes({"a.md": "x" * 200}))


def test_zip_symlink_is_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link.md")
        info.external_attr = 0o120777 << 16
        zf.writestr(info, "target.md")
    with pytest.raises(ValidationFailed, match="symbolic link"):
        sources.open_zip(buf.getvalue())


# ---- clipboard ---------------------------------------------------------------------------


def test_clipboard_splitting_and_titles() -> None:
    text = (
        "# Summarizer\nSummarize {{text}} in three bullets.\n\n---\n"
        "Title: Translator\nTranslate to French.\n###\n"
        "Rewrite this paragraph so it is shorter and clearer for a busy executive reader today.\n"
        "-----\n\n  \n---\n"
    )
    drafts = parse("clipboard", text)
    assert [d.title for d in drafts] == [
        "Summarizer",
        "Translator",
        "Rewrite this paragraph so it is shorter and…",
    ]
    assert drafts[0].body == "Summarize {{text}} in three bullets."
    assert drafts[2].body.startswith("Rewrite this paragraph")


def test_clipboard_custom_delimiter_single_and_empty() -> None:
    drafts = parse("clipboard", {"content": "one\n====\ntwo\n---\nstill two", "delimiter": "===="})
    assert [d.body for d in drafts] == ["one", "two\n---\nstill two"]
    assert len(parse("clipboard", {"content": "a\n---\nb", "single": True})) == 1
    assert clipboard.make_draft("short").title == "short"
    with pytest.raises(ValidationFailed, match="empty"):
        parse("clipboard", "  \n---\n ")


# ---- XLSX --------------------------------------------------------------------------------

needs_xlsx = pytest.mark.skipif(not HAS_OPENPYXL, reason="optional extra: promptvault[xlsx]")


def xlsx_bytes(sheets: dict[str, list[list[Any]]]) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@needs_xlsx
def test_xlsx_sheets_headers_and_cells() -> None:
    data = xlsx_bytes(
        {
            "Other": [["x"], ["y"]],
            "Prompts": [
                [],
                ["Title", "Body", "Tags", "Count"],
                ["Sheet Prompt", "Plan {{trip}}", "travel, plan", 3],
                [None, None, None, None],
                ["Formula", "=1+1", None, 2.0],
            ],
        }
    )
    drafts = parse("xlsx", {**b64(data), "sheet": "Prompts"})
    assert [(d.title, d.body, d.tags) for d in drafts] == [
        ("Sheet Prompt", "Plan {{trip}}", ["travel", "plan"]),
        ("Formula", "", []),  # formulas are never evaluated: no cached value, no body
    ]
    assert any("ignored: Count" in w for w in drafts[0].warnings)
    assert parse("xlsx", {**b64(data), "sheet": 2})[0].title == "Sheet Prompt"
    with pytest.raises(ValidationFailed, match="No column for"):
        parse("xlsx", b64(data))  # first sheet has no title/body columns
    with pytest.raises(ValidationFailed, match="not found"):
        parse("xlsx", {**b64(data), "sheet": "Nope"})
    with pytest.raises(ValidationFailed, match="valid ZIP"):
        parse("xlsx", b64(b"not a workbook"))
    with pytest.raises(ValidationFailed, match="readable .xlsx"):
        parse("xlsx", b64(zip_bytes({"a.txt": "x"})))
    empty = xlsx_bytes({"S": []})
    with pytest.raises(ValidationFailed, match="empty"):
        parse("xlsx", b64(empty))


def test_clipboard_handles_windows_line_endings() -> None:
    drafts = parse("clipboard", "Alpha body\r\n---\r\nBeta body\r\n###\r\nGamma body\r\n")
    assert [d.body for d in drafts] == ["Alpha body", "Beta body", "Gamma body"]
