"""CSV importer: header row required; delimiter detected (comma, semicolon, tab, pipe).

Source: a string, or {content | content_base64, mapping, delimiter}. Quoted cells may contain
newlines. Columns are matched to draft fields by alias; `mapping` ({field: column}) overrides.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from promptvault.importers import sources, tabular
from promptvault.importers.base import PromptDraft
from promptvault.services.errors import ValidationFailed

CANDIDATES = (",", ";", "\t", "|")
csv.field_size_limit(10_000_000)


def detect_delimiter(text: str) -> str:
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    counts = {d: first.count(d) for d in CANDIDATES}
    best = max(CANDIDATES, key=lambda d: counts[d])  # ties resolve to the earliest (comma)
    return best if counts[best] else ","


def _delimiter_option(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if value in ("tab", "\\t"):
        return "\t"
    if not isinstance(value, str) or len(value) != 1:
        raise ValidationFailed("delimiter must be a single character (or 'tab')")
    return value


class CsvImporter:
    name = "csv"
    description = "CSV with a header row (comma, semicolon, tab or pipe separated)"

    def parse(self, source: Any) -> list[PromptDraft]:
        text = sources.source_text(source)
        mapping = tabular.parse_mapping(sources.option(source, "mapping"))
        delimiter = _delimiter_option(sources.option(source, "delimiter")) or detect_delimiter(text)
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        headers: list[str] | None = None
        rows: list[list[str]] = []
        try:
            for record in reader:
                if headers is None:
                    if any(c.strip() for c in record):
                        headers = [c.strip() for c in record]
                    continue
                rows.append(record)
                if len(rows) > sources.MAX_PARSE_ROWS:
                    raise ValidationFailed(f"Too many rows (limit {sources.MAX_PARSE_ROWS})")
        except csv.Error as exc:
            raise ValidationFailed(f"Invalid CSV near line {reader.line_num}: {exc}") from exc
        if headers is None:
            raise ValidationFailed("CSV is empty: a header row is required")
        return tabular.rows_to_drafts(headers, rows, mapping)
