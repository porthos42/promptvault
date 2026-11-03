"""Parse one fetched file by its extension (shared by the GitHub and web page importers)."""

from __future__ import annotations

import json
import posixpath
from datetime import date, datetime
from typing import Any

import yaml

from promptvault.importers import markdown_import
from promptvault.importers.base import PromptDraft
from promptvault.importers.csv_import import CsvImporter
from promptvault.importers.json_import import JsonImporter
from promptvault.services.errors import ValidationFailed

MARKDOWN_EXTS = (".md", ".markdown")
TABULAR_EXTS = (".json", ".yaml", ".yml", ".csv")
SUPPORTED_EXTS = (*MARKDOWN_EXTS, *TABULAR_EXTS)


def extension(name: str) -> str:
    return posixpath.splitext(name.lower().split("?")[0].split("#")[0])[1]


def _json_default(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def parse_text(name: str, text: str, mapping: dict[str, str] | None = None) -> list[PromptDraft]:
    """Drafts from one file. Markdown files always give one draft (bad front-matter becomes a
    row error); JSON, YAML and CSV files raise ValidationFailed when they do not look like
    prompts (no title/body keys), so callers can skip them with a warning."""
    ext = extension(name)
    options: dict[str, Any] = {"mapping": mapping} if mapping else {}
    if ext in MARKDOWN_EXTS or ext == ".txt":
        return [markdown_import.parse_file(name, text)]
    if ext == ".json":
        return JsonImporter().parse({"content": text, **options})
    if ext in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValidationFailed(
                f"Invalid YAML ({getattr(exc, 'problem', None) or exc})"
            ) from exc
        return JsonImporter().parse({"content": json.dumps(data, default=_json_default), **options})
    if ext == ".csv":
        return CsvImporter().parse({"content": text, **options})
    raise ValidationFailed(f"Unsupported file type '{ext or name}'")
