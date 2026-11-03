"""XLSX importer (optional: needs `pip install prompt-vault[xlsx]`).

Source: {content_base64, sheet?, mapping?}. Reads one worksheet (name, or 1-based number; the
first by default) read-only with cached values: formulas are never evaluated, macros ignored.
The first non-empty row is the header.
"""

from __future__ import annotations

import io
from typing import Any

from promptvault.importers import sources, tabular
from promptvault.importers.base import PromptDraft
from promptvault.services.errors import ValidationFailed


class XlsxImporter:
    name = "xlsx"
    description = "Excel workbook (.xlsx), one sheet, header row required"

    def parse(self, source: Any) -> list[PromptDraft]:
        import openpyxl

        data = sources.source_bytes(source)
        mapping = tabular.parse_mapping(sources.option(source, "mapping"))
        sources.open_zip(data).close()  # size / entry / path checks before openpyxl touches it
        try:
            book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise ValidationFailed(f"Not a readable .xlsx workbook: {exc}") from exc
        try:
            sheet = self._sheet(book, sources.option(source, "sheet"))
            headers: list[str] | None = None
            rows: list[list[Any]] = []
            for values in sheet.iter_rows(values_only=True):
                row = list(values)
                if headers is None:
                    if any(c is not None and str(c).strip() for c in row):
                        headers = [str(c).strip() if c is not None else "" for c in row]
                    continue
                rows.append(row)
                if len(rows) > sources.MAX_PARSE_ROWS:
                    raise ValidationFailed(f"Too many rows (limit {sources.MAX_PARSE_ROWS})")
        finally:
            book.close()
        if headers is None:
            raise ValidationFailed("The sheet is empty: a header row is required")
        return tabular.rows_to_drafts(headers, rows, mapping)

    @staticmethod
    def _sheet(book: Any, wanted: Any) -> Any:
        names: list[str] = list(book.sheetnames)
        if wanted is None or wanted == "":
            return book[names[0]]
        if isinstance(wanted, str) and wanted in names:
            return book[wanted]
        try:
            index = int(wanted)
        except (TypeError, ValueError):
            index = 0
        if 1 <= index <= len(names):
            return book[names[index - 1]]
        raise ValidationFailed(f"Sheet {wanted!r} not found (sheets: {', '.join(names)})")
