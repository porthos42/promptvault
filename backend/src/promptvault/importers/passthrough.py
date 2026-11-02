"""Reference importer: the source already is JSON drafts. Used by tests and as a template.

Accepts a list of objects, or an object with a "prompts" list. Unknown keys are ignored; rows
that are not objects become drafts carrying an error so the preview can show them.
"""

from __future__ import annotations

from typing import Any

from promptvault.importers.base import PromptDraft
from promptvault.services.errors import ValidationFailed

_TEXT = (
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


class PassthroughImporter:
    name = "passthrough"

    def parse(self, source: Any) -> list[PromptDraft]:
        rows = source.get("prompts") if isinstance(source, dict) else source
        if not isinstance(rows, list):
            raise ValidationFailed("passthrough source must be a list of prompts or {prompts: []}")
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: Any) -> PromptDraft:
        if not isinstance(row, dict):
            return PromptDraft(errors=["row is not an object"])
        draft = PromptDraft()
        for key in _TEXT:
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                setattr(draft, key, value)
            else:
                draft.errors.append(f"{key}: must be a string")
        tags = row.get("tags")
        if isinstance(tags, list) and all(isinstance(t, str) for t in tags):
            draft.tags = list(tags)
        elif tags is not None:
            draft.errors.append("tags: must be a list of strings")
        return draft
