"""Clipboard importer: pasted text holding one or several prompts.

Source: a string, or {content, delimiter?, single?}. Default delimiter: a line of three or more
dashes, or a line that is just `###`. `delimiter` is a literal separator line (for example
`====`); `single: true` keeps everything as one prompt. A chunk starting with `# Heading` or
`Title: ...` uses it as the title; otherwise the title is the first words of the text.
"""

from __future__ import annotations

import re
from typing import Any

from promptvault.importers import sources
from promptvault.importers.base import PromptDraft
from promptvault.services.errors import PayloadTooLarge, ValidationFailed

DEFAULT_DELIMITER = re.compile(r"^[ \t]*(?:-{3,}|#{3})[ \t]*$", re.MULTILINE)
TITLE_LINE = re.compile(r"\A\s*(?:#{1,3}[ \t]+|title:[ \t]*)(.+?)[ \t]*\r?\n", re.IGNORECASE)
MAX_TITLE = 80


def split_chunks(text: str, delimiter: str | None) -> list[str]:
    if delimiter:
        pattern = re.compile(rf"^[ \t]*{re.escape(delimiter)}[ \t]*$", re.MULTILINE)
    else:
        pattern = DEFAULT_DELIMITER
    return [c.strip() for c in pattern.split(text) if c.strip()]


def make_draft(chunk: str) -> PromptDraft:
    match = TITLE_LINE.match(chunk + "\n")
    if match and chunk[match.end() :].strip():
        title, body = match.group(1).strip(), (chunk + "\n")[match.end() :].strip()
    else:
        words = chunk.split()
        title = " ".join(words[:8])
        if len(words) > 8 or len(title) > MAX_TITLE:
            title = title[: MAX_TITLE - 1].rstrip() + "…"
        body = chunk
    return PromptDraft(title=title, body=body)


class ClipboardImporter:
    name = "clipboard"
    description = (
        "Pasted text: one prompt, or several split by a --- / ### line (or your delimiter)"
    )

    def parse(self, source: Any) -> list[PromptDraft]:
        text = (
            sources.source_text(source).replace("\r\n", "\n").replace("\r", "\n")
        )  # Windows paste
        delimiter = sources.option(source, "delimiter")
        if delimiter is not None and not isinstance(delimiter, str):
            raise ValidationFailed("delimiter must be text")
        if sources.option(source, "single") is True:
            chunks = [text.strip()] if text.strip() else []
        else:
            chunks = split_chunks(text, delimiter or None)
        if not chunks:
            raise ValidationFailed("Nothing to import: the pasted text is empty")
        if len(chunks) > sources.MAX_PARSE_ROWS:
            raise PayloadTooLarge(f"Too many prompts (limit {sources.MAX_PARSE_ROWS})")
        return [make_draft(c) for c in chunks]
