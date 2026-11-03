"""Markdown importer: one prompt per file, YAML front-matter mapped to fields.

Sources: a string or {content, name?} (one file); {files: [{name, content}]}; or
{content_base64} holding a ZIP archive (or a single file). A folder is a list of files.
Title: front-matter `title`, else the first `# heading`, else the file name. The body is the text
after the front-matter (minus the heading used as title). Front-matter keys use the same aliases
as the tabular importers; `tags` may be a list or a comma separated string. Bad YAML makes that
one file an invalid row instead of failing the import.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

import yaml

from promptvault.importers import sources, tabular
from promptvault.importers.base import PromptDraft
from promptvault.services.errors import PayloadTooLarge, ValidationFailed

FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(?:(.*?)\r?\n)?---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
HEADING = re.compile(r"\A\s*#[ \t]+([^\r\n]*?)[ \t#]*(?:\r?\n|\Z)")


def _stem(name: str) -> str:
    base = posixpath.basename(name.replace("\\", "/"))
    return re.sub(r"[-_]+", " ", posixpath.splitext(base)[0]).strip()


def parse_file(name: str, text: str) -> PromptDraft:
    text = text.removeprefix("\ufeff")
    meta: dict[Any, Any] = {}
    errors: list[str] = []
    match = FRONT_MATTER.match(text)
    body = text
    if match:
        body = text[match.end() :]
        try:
            loaded = yaml.safe_load(match.group(1) or "")
        except yaml.YAMLError as exc:
            errors.append(f"front-matter: invalid YAML ({getattr(exc, 'problem', None) or exc})")
        else:
            if isinstance(loaded, dict):
                meta = loaded
            elif loaded is not None:
                errors.append("front-matter: must be a mapping of keys to values")
    headers = [str(k) for k in meta]
    columns, _ignored = tabular.resolve_columns(headers)
    columns.pop("body", None)  # the body is the text after the front-matter
    keys = list(meta.values())
    values = {field: keys[i] for field, i in columns.items()}
    draft = tabular.draft_from_values(values)
    draft.errors.extend(errors)
    if not draft.title:
        heading = HEADING.match(body)
        if heading:
            draft.title = heading.group(1).strip()
            body = body[heading.end() :]
        else:
            draft.title = _stem(name)
    draft.body = body.strip()
    return draft


class MarkdownImporter:
    name = "markdown"
    description = (
        "Markdown files (one prompt per file) with optional YAML front-matter; ZIP or list"
    )

    def parse(self, source: Any) -> list[PromptDraft]:
        drafts: list[PromptDraft] = []
        for name, raw in self._files(source):
            try:
                text = raw if isinstance(raw, str) else sources.decode_text(raw)
            except ValidationFailed as exc:
                drafts.append(PromptDraft(title=_stem(name), errors=[f"{name}: {exc.detail}"]))
                continue
            drafts.append(parse_file(name, text))
            if len(drafts) > sources.MAX_PARSE_ROWS:
                raise PayloadTooLarge(f"Too many files (limit {sources.MAX_PARSE_ROWS})")
        return drafts

    @staticmethod
    def _files(source: Any) -> list[tuple[str, str | bytes]]:
        if isinstance(source, str):
            return [("prompt.md", source)]
        items = source.get("files") if isinstance(source, dict) else source
        if isinstance(items, list):
            out: list[tuple[str, str | bytes]] = []
            for item in items:
                if not (
                    isinstance(item, dict)
                    and isinstance(item.get("name"), str)
                    and isinstance(item.get("content"), str)
                ):
                    raise ValidationFailed("files must be a list of {name, content} objects")
                out.append((item["name"], item["content"]))
            return out
        if isinstance(source, dict) and "content_base64" in source:
            data = sources.source_bytes(source)
            if data.startswith(b"PK"):
                return list(sources.zip_files(data))
            return [(str(source.get("name") or "prompt.md"), data)]
        if isinstance(source, dict) and isinstance(source.get("content"), str):
            return [(str(source.get("name") or "prompt.md"), source["content"])]
        raise ValidationFailed(
            "Markdown source needs `content`, `files` ([{name, content}]) "
            "or a ZIP in `content_base64`"
        )
