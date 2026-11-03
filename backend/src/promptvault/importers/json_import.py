"""JSON importer: a list of prompt objects, or an object holding a `prompts` list.

Source forms: the parsed JSON itself; a JSON string; or {content | content_base64, mapping}
(also {prompts, mapping}). Keys are matched to draft fields by alias (see tabular.ALIASES); an
explicit `mapping` ({field: key}) overrides. Also reads the shape of the prompt API/export
(`category` as {slug, name}, `tags` as a list).
"""

from __future__ import annotations

import json
from typing import Any

from promptvault.importers import sources, tabular
from promptvault.importers.base import PromptDraft
from promptvault.services.errors import ValidationFailed


class JsonImporter:
    name = "json"
    description = 'JSON: a list of prompt objects, or {"prompts": [...]}'

    def parse(self, source: Any) -> list[PromptDraft]:
        mapping = None
        data: Any = source
        if isinstance(source, str):
            data = self._loads(source)
        elif isinstance(source, dict) and ("content" in source or "content_base64" in source):
            mapping = tabular.parse_mapping(source.get("mapping"))
            data = self._loads(sources.source_text(source))
        elif isinstance(source, dict) and "mapping" in source:
            mapping = tabular.parse_mapping(source.get("mapping"))
        rows = self._rows(data)
        if len(rows) > sources.MAX_PARSE_ROWS:
            raise ValidationFailed(f"Too many rows (limit {sources.MAX_PARSE_ROWS})")
        headers: list[str] = []
        for row in rows:
            if isinstance(row, dict):
                headers.extend(k for k in row if isinstance(k, str) and k not in headers)
        columns, ignored = tabular.resolve_columns(headers, mapping)
        tabular.require_columns(columns, headers)
        drafts: list[PromptDraft] = []
        for row in rows:
            if isinstance(row, dict):
                drafts.append(
                    tabular.draft_from_values({f: row.get(headers[i]) for f, i in columns.items()})
                )
            else:
                drafts.append(PromptDraft(errors=["row is not an object"]))
        if drafts:
            drafts[0].warnings.extend(tabular.mapping_notes(columns, ignored, headers))
        return drafts

    @staticmethod
    def _loads(text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationFailed(
                f"Invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})"
            ) from exc

    @staticmethod
    def _rows(data: Any) -> list[Any]:
        if isinstance(data, dict):
            for key in ("prompts", "items"):
                if isinstance(data.get(key), list):
                    return list(data[key])
            if any(k in data for k in ("title", "name", "body", "prompt")):
                return [data]  # a single prompt object
        if isinstance(data, list):
            return data
        raise ValidationFailed('JSON source must be a list of prompts or {"prompts": [...]}')
