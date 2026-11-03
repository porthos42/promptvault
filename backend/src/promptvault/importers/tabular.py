"""Column / key mapping shared by the tabular importers (CSV, XLSX, JSON) and Markdown
front-matter: header aliases, explicit mappings, cell coercion and tag splitting."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from promptvault.importers.base import PromptDraft
from promptvault.services.errors import ValidationFailed

TEXT_FIELDS = (
    "title",
    "body",
    "description",
    "category",
    "difficulty",
    "prompt_type",
    "model_hints",
    "output_format",
    "disclaimer",
    "source_url",
    "license",
)
FIELDS = (*TEXT_FIELDS, "tags")

# draft field -> accepted header names (compared after normalize_header)
ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "name", "prompt_name", "prompt_title", "heading"),
    "body": ("body", "prompt", "text", "content", "prompt_text", "template"),
    "description": ("description", "summary", "details", "about"),
    "category": ("category", "category_slug", "topic"),
    "tags": ("tags", "tag", "labels", "keywords"),
    "difficulty": ("difficulty", "level"),
    "prompt_type": ("prompt_type", "type", "kind"),
    "model_hints": ("model_hints", "model", "models", "model_hint"),
    "output_format": ("output_format", "format", "output"),
    "disclaimer": ("disclaimer", "warning", "notice"),
    "source_url": ("source_url", "url", "link", "source_link"),
    "license": ("license", "licence", "licence_type"),
}
_TAG_SPLIT = re.compile(r"[,;|]")


def normalize_header(name: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(name or "").strip().lower())


def resolve_columns(
    headers: list[str], mapping: dict[str, str] | None = None
) -> tuple[dict[str, int], list[str]]:
    """Map draft fields to header positions. An explicit mapping ({field: header}) wins; the
    rest is auto-detected by alias. Returns (field -> index, ignored headers)."""
    norm = [normalize_header(h) for h in headers]
    found: dict[str, int] = {}
    for field, column in (mapping or {}).items():
        if field not in FIELDS:
            raise ValidationFailed(
                f"mapping: unknown field '{field}' (fields: {', '.join(FIELDS)})"
            )
        key = normalize_header(column)
        if key not in norm:
            raise ValidationFailed(
                f"mapping: column '{column}' not found "
                f"(columns: {', '.join(h for h in headers if h)})"
            )
        found[field] = norm.index(key)
    taken = set(found.values())
    for field, aliases in ALIASES.items():
        if field in found:
            continue
        for alias in aliases:
            if alias in norm and norm.index(alias) not in taken:
                found[field] = norm.index(alias)
                taken.add(found[field])
                break
    ignored = [h for i, h in enumerate(headers) if i not in taken and str(h or "").strip()]
    return found, ignored


def coerce_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if v is not None and str(v).strip()]
    return [t.strip() for t in _TAG_SPLIT.split(str(value)) if t.strip()]


def coerce_text(value: Any) -> str | None:
    """Cells become text; numbers keep their natural form, dates are not expected."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def draft_from_values(values: dict[str, Any]) -> PromptDraft:
    """Build a draft from {field: raw value}; values that cannot be text become row errors."""
    draft = PromptDraft()
    for field in TEXT_FIELDS:
        raw = values.get(field)
        if field == "category" and isinstance(raw, dict):
            raw = raw.get("slug") or raw.get("name")  # PromptVault API/export shape
        if isinstance(raw, dict | list):
            draft.errors.append(f"{field}: must be text")
            continue
        text = coerce_text(raw)
        if text is not None:
            setattr(draft, field, text)
    if isinstance(values.get("tags"), dict):
        draft.errors.append("tags: must be a list or comma separated text")
    else:
        draft.tags = coerce_tags(values.get("tags"))
    return draft


def require_columns(
    columns: dict[str, int], headers: list[str], require: tuple[str, ...] = ("title", "body")
) -> None:
    missing = [f for f in require if f not in columns]
    if missing:
        shown = ", ".join(h for h in headers if str(h or "").strip()) or "none"
        raise ValidationFailed(
            f"No column for: {', '.join(missing)}. Columns found: {shown}. "
            "Pass `mapping` as {field: column}."
        )


def mapping_notes(columns: dict[str, int], ignored: list[str], headers: list[str]) -> list[str]:
    notes = ["columns mapped: " + ", ".join(f"{f}<-{headers[i]}" for f, i in columns.items())]
    if ignored:
        notes.append(f"columns ignored: {', '.join(ignored)}")
    return notes


GUARDED = ("=", "+", "-", "@", "\t", "\r")


def unguard(value: Any) -> Any:
    """Undo the formula guard that the CSV/XLSX export adds (a leading apostrophe before a
    cell that starts with = + - @ tab or CR), so an exported file reads back unchanged."""
    if isinstance(value, str) and len(value) > 1 and value[0] == "'" and value[1] in GUARDED:
        return value[1:]
    return value


def rows_to_drafts(
    headers: list[str], rows: Iterable[list[Any]], mapping: dict[str, str] | None = None
) -> list[PromptDraft]:
    """Turn a header + rows table into drafts. Blank rows are dropped."""
    columns, ignored = resolve_columns(headers, mapping)
    require_columns(columns, headers)
    drafts: list[PromptDraft] = []
    for row in rows:
        if not any(str(c).strip() for c in row if c is not None):
            continue
        values = {f: unguard(row[i]) if i < len(row) else None for f, i in columns.items()}
        drafts.append(draft_from_values(values))
    if drafts:
        drafts[0].warnings.extend(mapping_notes(columns, ignored, headers))
    return drafts


def parse_mapping(raw: Any) -> dict[str, str] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
    ):
        raise ValidationFailed("mapping must be an object of {draft field: column name}")
    return dict(raw)
