"""Export: select prompts, flatten them to records and write JSON, CSV, XLSX, a Markdown ZIP
or folder, and a single-prompt share snippet (docs/SPEC.md 3.6).

Framework-free: shared by the HTTP API and the CLI, no FastAPI, no Typer. Large exports never
build one big string: records are read in batches of 500, each batch in its own short database
session (so no session is held open while a client downloads), and the writers are generators
of byte chunks. XLSX and ZIP need random access and are built in a spooled temporary file
(memory up to 8 MiB, then disk) that is streamed afterwards.

Everything written is deterministic for the same data: records are ordered by title then id,
ZIP entries carry a fixed timestamp, and `Options.now` pins `exported_at`.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import re
import tempfile
import textwrap
import unicodedata
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from promptvault import __version__
from promptvault.models import Category, Prompt, PromptRevision
from promptvault.services import prompts as svc
from promptvault.services import variables as var_svc
from promptvault.services.errors import NotFoundError, PayloadTooLarge, ValidationFailed

FORMAT_ID = "promptvault-export"
FORMAT_VERSION = 1
BATCH = 500
SPOOL_BYTES = 8 * 1024 * 1024
CHUNK = 64 * 1024
XLSX_CELL_LIMIT = 32767
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
GUARD_CHARS = ("=", "+", "-", "@", "\t", "\r")  # a spreadsheet may read these as a formula

SessionOpener = Callable[[], Session]
Spool = tempfile.SpooledTemporaryFile[bytes]


# ---- formats -------------------------------------------------------------------------------


@dataclass(frozen=True)
class FormatInfo:
    name: str
    extension: str
    media_type: str
    description: str
    binary: bool
    requires: str | None = None  # optional Python module


FORMATS: dict[str, FormatInfo] = {
    f.name: f
    for f in (
        FormatInfo(
            "json", "json", "application/json", "Lossless JSON the json importer reads back", False
        ),
        FormatInfo("csv", "csv", "text/csv; charset=utf-8", "CSV for spreadsheets", False),
        FormatInfo(
            "xlsx",
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "Excel workbook (optional extra: prompt-vault[xlsx])",
            True,
            requires="openpyxl",
        ),
        FormatInfo(
            "markdown",
            "zip",
            "application/zip",
            "ZIP with one Markdown file per prompt (YAML front-matter)",
            True,
        ),
    )
}
FORMAT_ALIASES = {"md": "markdown"}
XLSX_HINT = "install the optional extra: pip install 'prompt-vault[xlsx]'"


def unavailable_reason(info: FormatInfo) -> str | None:
    if info.requires and importlib.util.find_spec(info.requires) is None:
        return XLSX_HINT
    return None


def describe_formats() -> list[dict[str, Any]]:
    out = []
    for info in FORMATS.values():
        reason = unavailable_reason(info)
        out.append(
            {
                "name": info.name,
                "extension": info.extension,
                "media_type": info.media_type,
                "description": info.description,
                "available": reason is None,
                "reason": reason,
            }
        )
    return out


def get_format(name: str) -> FormatInfo:
    """Unknown format -> 422; a format whose optional dependency is missing -> 404."""
    key = FORMAT_ALIASES.get(name.strip().lower(), name.strip().lower())
    info = FORMATS.get(key)
    if info is None:
        raise ValidationFailed(f"Unknown export format '{name}' (formats: {', '.join(FORMATS)})")
    reason = unavailable_reason(info)
    if reason:
        raise NotFoundError(f"Export format '{info.name}' is not available: {reason}")
    return info


# ---- selection -----------------------------------------------------------------------------


@dataclass
class Selection:
    """What to export: the list/search filters and/or an explicit id list. Trashed prompts are
    only included when asked for."""

    filters: svc.ListFilters = field(default_factory=svc.ListFilters)
    ids: list[str] | None = None
    include_trashed: bool = False


@dataclass
class Plan:
    ids: list[str]  # in output order
    missing: list[str]  # requested ids that matched nothing (unknown, or trashed and not included)
    filters: dict[str, Any]


def describe_filters(sel: Selection) -> dict[str, Any]:
    f = sel.filters
    out: dict[str, Any] = {}
    for key in ("q", "category", "difficulty", "prompt_type", "favorite", "source", "model"):
        value = getattr(f, key)
        if value not in (None, ""):
            out[key] = value
    if f.tags:
        out["tags"] = list(f.tags)
        out["tags_mode"] = f.tags_mode
    if f.has_variables is not None:
        out["has_variables"] = f.has_variables
    if sel.ids is not None:
        out["ids_requested"] = len(sel.ids)
    if sel.include_trashed:
        out["include_trashed"] = True
    return out


def _search_keys(session: Session, f: svc.ListFilters) -> list[tuple[str, str]]:
    """Full-text search goes through the list service so export and the search box agree."""
    keys: list[tuple[str, str]] = []
    cursor: str | None = None
    while True:
        res = svc.list_prompts(session, replace(f, sort="title"), BATCH, cursor)
        keys += [(p.title, p.id) for p in res.items]
        cursor = res.next_cursor
        if cursor is None:
            return keys


def prepare(session: Session, sel: Selection, max_rows: int | None = None) -> Plan:
    """Resolve the selection to an ordered id list. Reads only; raises PayloadTooLarge (413)
    when more than `max_rows` prompts match."""
    f = sel.filters
    ids = list(dict.fromkeys(sel.ids)) if sel.ids is not None else None
    if f.q:
        keys: list[tuple[str, str]] = []
        for trash in (False, True) if sel.include_trashed else (False,):
            keys += _search_keys(session, replace(f, trash=trash))
        if ids is not None:
            keys = [k for k in keys if k[1] in set(ids)]
    else:
        conds = svc._filter_conditions(session, f)  # noqa: SLF001  (shared with the list endpoint)
        if sel.include_trashed:
            conds = conds[1:]  # the first condition is "live only"
        if ids is not None:
            conds.append(Prompt.id.in_(ids))
        keys = [(t, i) for t, i in session.execute(select(Prompt.title, Prompt.id).where(*conds))]
    keys.sort(key=lambda k: (k[0].casefold(), k[1]))
    if max_rows is not None and len(keys) > max_rows:
        raise PayloadTooLarge(
            f"The selection has {len(keys)} prompts; the export limit is {max_rows} "
            "(PV_EXPORT_MAX_ROWS). Narrow the filters."
        )
    found = {i for _, i in keys}
    return Plan(
        ids=[i for _, i in keys],
        missing=[i for i in ids if i not in found] if ids is not None else [],
        filters=describe_filters(sel),
    )


# ---- records -------------------------------------------------------------------------------


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def to_record(p: Prompt, version: int | None) -> dict[str, Any]:
    """One prompt in export shape: the same keys the json importer reads (category as
    {slug, name}, tags as a list) plus metadata that only an export carries."""
    return {
        "id": p.id,
        "seed_id": p.seed_id,
        "title": p.title,
        "body": p.body,
        "description": p.description,
        "category": {"slug": p.category.slug, "name": p.category.name} if p.category else None,
        "tags": sorted(t.name for t in p.tags),
        "variables": p.variables,
        "model_hints": p.model_hints,
        "output_format": p.output_format,
        "difficulty": p.difficulty,
        "prompt_type": p.prompt_type,
        "disclaimer": p.disclaimer,
        "source": p.source,
        "source_url": p.source_url,
        "license": p.license,
        "is_favorite": p.is_favorite,
        "rating": p.rating,
        "use_count": p.use_count,
        "last_used_at": iso(p.last_used_at),
        "created_at": iso(p.created_at),
        "updated_at": iso(p.updated_at),
        "deleted_at": iso(p.deleted_at),
        "version": version,
    }


def load_records(session: Session, ids: list[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    found = {p.id: p for p in session.scalars(svc._load(select(Prompt).where(Prompt.id.in_(ids))))}  # noqa: SLF001
    versions = dict(
        session.execute(
            select(PromptRevision.prompt_id, func.max(PromptRevision.version))
            .where(PromptRevision.prompt_id.in_(ids))
            .group_by(PromptRevision.prompt_id)
        ).all()
    )
    return [to_record(found[i], versions.get(i)) for i in ids if i in found]


def iter_records(open_session: SessionOpener, ids: list[str]) -> Iterator[dict[str, Any]]:
    for start in range(0, len(ids), BATCH):
        with open_session() as session:  # one short session per batch, never held across yields
            batch = load_records(session, ids[start : start + BATCH])
        yield from batch


def category_rows(session: Session) -> list[dict[str, Any]]:
    """All categories, parents before children (so they can be created in this order)."""
    cats = list(session.scalars(select(Category).order_by(Category.slug)))
    slug_of = {c.id: c.slug for c in cats}
    by_parent: dict[int | None, list[Category]] = {}
    for c in cats:
        by_parent.setdefault(c.parent_id if c.parent_id in slug_of else None, []).append(c)
    out: list[dict[str, Any]] = []
    stack = list(reversed(by_parent.get(None, [])))
    while stack:
        c = stack.pop()
        out.append(
            {
                "slug": c.slug,
                "name": c.name,
                "parent": slug_of.get(c.parent_id) if c.parent_id else None,
                "icon": c.icon,
                "sort_order": c.sort_order,
            }
        )
        stack.extend(reversed(by_parent.get(c.id, [])))
    return out


# ---- options and result --------------------------------------------------------------------


@dataclass(frozen=True)
class Options:
    pretty: bool = False  # JSON: indented
    bom: bool = True  # CSV: UTF-8 byte order mark (Excel needs it to read UTF-8)
    raw: bool = False  # CSV/XLSX: switch the formula guard off
    now: datetime | None = None  # pin exported_at (tests)


@dataclass
class Export:
    format: FormatInfo
    count: int
    chunks: Iterator[bytes]
    warnings: list[str] = field(default_factory=list)

    def read(self) -> bytes:
        return b"".join(self.chunks)


def run(
    open_session: SessionOpener, fmt: str, plan: Plan, options: Options | None = None
) -> Export:
    """Start an export. JSON and CSV stream lazily; XLSX and ZIP are built before returning."""
    options = options or Options()
    info = get_format(fmt)
    count = len(plan.ids)
    if info.name == "json":
        return Export(info, count, _json_chunks(open_session, plan, options))
    if info.name == "csv":
        return Export(info, count, _csv_chunks(open_session, plan, options))
    if info.name == "xlsx":
        spool, warnings = _build_xlsx(open_session, plan, options)
    else:
        spool, warnings = _build_zip(open_session, plan)
    return Export(info, count, _spool_chunks(spool), warnings)


# ---- JSON ----------------------------------------------------------------------------------


def _dumps(value: Any, pretty: bool) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2 if pretty else None, sort_keys=False)


def _json_chunks(open_session: SessionOpener, plan: Plan, options: Options) -> Iterator[bytes]:
    pretty = options.pretty
    with open_session() as session:
        categories = category_rows(session)
    head = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "exported_at": iso(options.now or datetime.now(UTC)),
        "app_version": __version__,
        "count": len(plan.ids),
        "filters": plan.filters,
        "categories": categories,
    }
    text = _dumps(head, pretty)
    yield (
        text[: text.rindex("}")].rstrip() + (',\n  "prompts": [' if pretty else ',"prompts":[')
    ).encode()
    first = True
    for rec in iter_records(open_session, plan.ids):
        item = _dumps(rec, pretty)
        if pretty:
            item = textwrap.indent(item, "    ")
        sep = "" if first else ","
        yield f"{sep}\n{item}".encode() if pretty else f"{sep}{item}".encode()
        first = False
    yield (b"\n  ]\n}\n" if pretty else b"]}\n")


# ---- CSV and XLSX --------------------------------------------------------------------------

# Header names are importer aliases (importers/tabular.py), so the file reads back as it is.
COLUMNS = (
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
    "source",
    "source_url",
    "variables",
    "is_favorite",
    "rating",
    "use_count",
    "last_used_at",
    "created_at",
    "updated_at",
    "deleted_at",
    "id",
    "seed_id",
    "version",
)
WIDTHS = {"title": 40, "body": 80, "description": 40, "category": 22, "tags": 30, "id": 38}


def guard_cell(value: str) -> str:
    """Neutralize spreadsheet formula injection: a leading apostrophe. The csv and xlsx
    importers strip it again (tabular.unguard)."""
    return "'" + value if value.startswith(GUARD_CHARS) else value


def flat_values(rec: dict[str, Any]) -> list[Any]:
    """One record as spreadsheet cells (text stays text, booleans and numbers keep their type)."""
    out: list[Any] = []
    for col in COLUMNS:
        value = rec[col]
        if col == "category":
            value = value["slug"] if value else None
        elif col == "tags":
            value = ", ".join(value) or None
        elif col == "variables":
            value = _dumps(value, False) if value else None
        out.append(value)
    return out


def _csv_cell(value: Any, raw: bool) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    return text if raw else guard_cell(text)


def _csv_chunks(open_session: SessionOpener, plan: Plan, options: Options) -> Iterator[bytes]:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")  # RFC 4180; written as bytes, so no translation
    writer.writerow(COLUMNS)
    yield (b"\xef\xbb\xbf" if options.bom else b"") + buf.getvalue().encode()
    for start in range(0, len(plan.ids), BATCH):
        buf.seek(0)
        buf.truncate()
        for rec in iter_records(open_session, plan.ids[start : start + BATCH]):
            writer.writerow(_csv_cell(v, options.raw) for v in flat_values(rec))
        yield buf.getvalue().encode()


def _fit_cell(text: str, limit: int = XLSX_CELL_LIMIT) -> tuple[str, int]:
    """Cut text to the XLSX cell limit with a visible marker. Returns (text, characters lost)."""
    if len(text) <= limit:
        return text, 0
    template = "\n[truncated by Prompt Vault: {n} more characters; use the JSON export]"
    keep = limit - len(template.format(n=len(text)))
    omitted = len(text) - keep
    return text[:keep] + template.format(n=omitted), omitted


def _build_xlsx(
    open_session: SessionOpener, plan: Plan, options: Options
) -> tuple[Spool, list[str]]:
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Prompts")
    ws.freeze_panes = "A2"
    for i, col in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = WIDTHS.get(col, 16)
    bold, wrap = Font(bold=True), Alignment(wrap_text=True, vertical="top")

    def text_cell(text: str, *, font: Any = None, align: Any = None) -> Any:
        cell = WriteOnlyCell(ws, value=text)
        cell.data_type = "s"  # always text: openpyxl would turn "=..." into a real formula
        if font is not None:
            cell.font = font
        if align is not None:
            cell.alignment = align
        return cell

    ws.append([text_cell(c, font=bold) for c in COLUMNS])
    notes: list[tuple[int, str, str, str]] = []  # (row, title, column, what happened)
    row_no = 1
    for rec in iter_records(open_session, plan.ids):
        row_no += 1
        cells: list[Any] = []
        for col, value in zip(COLUMNS, flat_values(rec), strict=True):
            if not isinstance(value, str):
                cells.append(value)
                continue
            # XML cannot carry a bare CR (readers turn CR and CRLF into LF), so write LF only
            value = value.replace("\r\n", "\n").replace("\r", "\n")
            if ILLEGAL_CHARACTERS_RE.search(value):
                value = ILLEGAL_CHARACTERS_RE.sub("", value)
                notes.append((row_no, rec["title"], col, "control characters removed"))
            if not options.raw:
                value = guard_cell(value)
            value, lost = _fit_cell(value)
            if lost:
                notes.append((row_no, rec["title"], col, f"cut at the cell limit ({lost} lost)"))
            cells.append(text_cell(value, align=wrap if col in ("body", "description") else None))
        ws.append(cells)
    warnings = [f"row {r} ({t[:60]!r}), column {c}: {what}" for r, t, c, what in notes]
    if notes:
        sheet = wb.create_sheet("Notes")
        sheet.append(["Row", "Prompt", "Column", "What happened"])
        sheet.append(
            ["", "", "", "Some cells could not be written as they are. Use the JSON export."]
        )
        for note in notes:
            sheet.append([note[0], guard_cell(note[1]), note[2], note[3]])
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)  # noqa: SIM115
    wb.save(spool)
    spool.seek(0)
    return spool, warnings


def _spool_chunks(spool: Spool) -> Iterator[bytes]:
    try:
        while chunk := spool.read(CHUNK):
            yield chunk
    finally:
        spool.close()


# ---- Markdown ------------------------------------------------------------------------------

# Windows refuses these names (with or without an extension)
RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)
STEM_LIMIT = 60
UNCATEGORISED = "uncategorised"


def slugify_name(text: str, limit: int = STEM_LIMIT) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:limit].strip("-")


def safe_stem(text: str, fallback: str, limit: int = STEM_LIMIT) -> str:
    stem = slugify_name(text, limit) or fallback
    return f"{stem}-prompt" if stem in RESERVED_NAMES else stem


def unique_path(directory: str, stem: str, used: set[str]) -> str:
    """`dir/stem.md`, or `dir/stem-2.md`, ... when taken (compared case-insensitively, as
    Windows and macOS file systems do)."""
    n = 1
    while True:
        suffix = "" if n == 1 else f"-{n}"
        name = f"{directory}/{stem[: STEM_LIMIT - len(suffix)]}{suffix}.md"
        if name.lower() not in used:
            used.add(name.lower())
            return name
        n += 1


class _Dumper(yaml.SafeDumper):
    """Multi-line strings as readable `|` blocks (PyYAML falls back to quoting when a block
    cannot represent the text exactly)."""


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_representer)


def markdown_text(rec: dict[str, Any]) -> str:
    """One prompt as a Markdown file. Front-matter keys are importer aliases, so it re-imports."""
    meta: dict[str, Any] = {
        "title": rec["title"],
        "category": rec["category"]["slug"] if rec["category"] else None,
        "tags": rec["tags"],
        "difficulty": rec["difficulty"],
        "type": rec["prompt_type"],
        "model_hints": rec["model_hints"],
        "output_format": rec["output_format"],
        "license": rec["license"],
        "source_url": rec["source_url"],
        "disclaimer": rec["disclaimer"],
        "description": rec["description"],
    }
    meta = {k: v for k, v in meta.items() if v not in (None, "", [])}
    front = yaml.dump(
        meta,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10**6,
    )
    return f"---\n{front}---\n\n{rec['body']}\n"


def markdown_files(open_session: SessionOpener, plan: Plan) -> Iterator[tuple[str, bytes]]:
    """(relative path, content) per prompt: `<category-slug>/<title-slug>.md`."""
    used: set[str] = set()
    for rec in iter_records(open_session, plan.ids):
        cat = rec["category"]["slug"] if rec["category"] else UNCATEGORISED
        directory = safe_stem(cat, "category")
        stem = safe_stem(rec["title"], f"prompt-{rec['id'][:8]}")
        yield unique_path(directory, stem, used), markdown_text(rec).encode("utf-8")


def _build_zip(open_session: SessionOpener, plan: Plan) -> tuple[Spool, list[str]]:
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)  # noqa: SIM115
    with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name, data in markdown_files(open_session, plan):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.create_system = 3  # same bytes on every platform
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data, compresslevel=6)
    spool.seek(0)
    return spool, []


def parse_values(items: list[str] | None) -> dict[str, str]:
    """`name=value` pairs (the CLI `--values` and the API `values` parameter)."""
    values: dict[str, str] = {}
    for item in items or []:
        name, sep, value = item.partition("=")
        if not sep or not name.strip():
            raise ValidationFailed(f"values: '{item}' is not name=value")
        values[name.strip()] = value
    return values


# ---- share snippet -------------------------------------------------------------------------

SHARE_FORMATS = ("markdown", "text", "json")


def _variable_line(v: dict[str, Any]) -> str:
    extra = []
    if v.get("default"):
        extra.append(f"default: {v['default']}")
    if v.get("options"):
        extra.append("options: " + ", ".join(v["options"]))
    label = v.get("label") or v["name"]
    return f"{label}" + (f" ({'; '.join(extra)})" if extra else "")


def _source_line(rec: dict[str, Any]) -> str:
    parts = []
    if rec.get("license"):
        parts.append(f"License: {rec['license']}")
    if rec.get("source_url"):
        parts.append(f"Source: {rec['source_url']}")
    return " | ".join(parts)


def share_snippet(
    rec: dict[str, Any], fmt: str, values: dict[str, str] | None = None
) -> tuple[str, list[str]]:
    """A copy-paste block for one prompt. With `values` the variables are filled in (the ones
    left without a value stay as `{{name}}` and are listed). Returns (text, missing names)."""
    if fmt not in SHARE_FORMATS:
        raise ValidationFailed(
            f"Unknown share format '{fmt}' (formats: {', '.join(SHARE_FORMATS)})"
        )
    variables: list[dict[str, Any]] = rec["variables"]
    body, missing = rec["body"], [v["name"] for v in variables]
    if values:
        unknown = sorted(set(values) - set(missing))
        if unknown:
            raise ValidationFailed(
                f"Unknown variable(s): {', '.join(unknown)} "
                f"(this prompt has: {', '.join(missing) or 'none'})"
            )
        body, missing = var_svc.render(body, variables, values)
    open_vars = [v for v in variables if v["name"] in missing]
    source = _source_line(rec)
    if fmt == "json":
        doc = {
            "title": rec["title"],
            "description": rec["description"] or None,
            "body": body,
            "variables": [
                {k: v[k] for k in ("name", "label", "type", "default", "options") if k in v}
                for v in open_vars
            ],
            "category": rec["category"]["slug"] if rec["category"] else None,
            "tags": rec["tags"],
            "license": rec["license"],
            "source_url": rec["source_url"],
            "disclaimer": rec["disclaimer"],
        }
        return _dumps(doc, True), missing
    if fmt == "text":
        lines = [rec["title"], "", body]
        if open_vars:
            lines += [
                "",
                "Variables:",
                *(f"- {{{{{v['name']}}}}}: {_variable_line(v)}" for v in open_vars),
            ]
        if rec["disclaimer"]:
            lines += ["", f"Note: {rec['disclaimer']}"]
        if source:
            lines += ["", source]
        return "\n".join(lines) + "\n", missing
    longest = max((len(m) for m in re.findall(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)  # longer than any backtick run inside the prompt
    md = [f"### {rec['title']}", ""]
    if rec["description"]:
        md += [rec["description"], ""]
    md += [f"{fence}text", body, fence]
    if open_vars:
        md += [
            "",
            "**Variables**",
            "",
            *(f"- `{{{{{v['name']}}}}}`: {_variable_line(v)}" for v in open_vars),
        ]
    if rec["disclaimer"]:
        md += ["", f"> {rec['disclaimer']}"]
    if source:
        md += ["", f"_{source}_"]
    return "\n".join(md) + "\n", missing


# ---- file names ----------------------------------------------------------------------------


def download_name(info: FormatInfo, now: datetime | None = None) -> str:
    return f"promptvault-export-{(now or datetime.now(UTC)):%Y%m%d}.{info.extension}"


def single_name(rec: dict[str, Any], extension: str) -> str:
    return f"promptvault-{safe_stem(rec['title'], 'prompt-' + rec['id'][:8])}.{extension}"
