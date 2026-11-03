"""Build an importer `source` from a local path or stdin (used by the `import` CLI command)."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Any

from promptvault.importers import sources
from promptvault.services.errors import ValidationFailed

BINARY_IMPORTERS = frozenset({"xlsx"})
# importers that read a URL, and the extra source options each one accepts
URL_OPTIONS: dict[str, frozenset[str]] = {
    "github": frozenset(),
    "url": frozenset({"mode"}),
    "huggingface": frozenset({"config", "split", "limit"}),
}
MAX_FILE_BYTES = 50 * 1024 * 1024


def _read(path: Path) -> bytes:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValidationFailed(f"{path} is larger than {MAX_FILE_BYTES} bytes")
    return path.read_bytes()


def build_source(
    importer: str,
    path: str,
    *,
    mapping: dict[str, str] | None = None,
    sheet: str | None = None,
    delimiter: str | None = None,
    url_options: dict[str, Any] | None = None,
) -> Any:
    """URL importers (github, url, huggingface) take an http(s) URL and the options in
    `URL_OPTIONS`. Otherwise `-` reads stdin; a directory (markdown importer) becomes a list
    of files; any other file is sent as text, or as base64 for binary formats and ZIP archives."""
    options: dict[str, Any] = {}
    if mapping:
        options["mapping"] = mapping
    if sheet:
        options["sheet"] = sheet
    if delimiter:
        options["delimiter"] = delimiter

    extra = {k: v for k, v in (url_options or {}).items() if v is not None}
    if importer in URL_OPTIONS:
        if not path.lower().startswith(("http://", "https://")):
            raise ValidationFailed(f"The {importer} importer needs an http(s) URL, not '{path}'")
        unknown = sorted(set(extra) - URL_OPTIONS[importer])
        if unknown:
            raise ValidationFailed(
                f"The {importer} importer has no option(s): {', '.join(unknown)}"
            )
        return {"url": path, **extra, **options}
    if extra:
        raise ValidationFailed(f"Option(s) {', '.join(sorted(extra))} only apply to URL importers")
    if path == "-":
        return {"content": sources.decode_text(sys.stdin.buffer.read()), **options}
    target = Path(path)
    if not target.exists():
        raise ValidationFailed(f"Path not found: {path}")
    if target.is_dir():
        if importer != "markdown":
            raise ValidationFailed(f"The {importer} importer reads a file, not a folder")
        files = []
        for f in sorted(target.rglob("*")):
            rel = f.relative_to(target).as_posix()
            is_text = f.is_file() and f.suffix.lower() in sources.MARKDOWN_SUFFIXES
            if is_text and not sources.is_junk(rel):
                files.append({"name": rel, "content": sources.decode_text(_read(f))})
        if not files:
            raise ValidationFailed(f"No .md, .markdown or .txt files found in {path}")
        return {"files": files, **options}
    data = _read(target)
    if importer in BINARY_IMPORTERS or target.suffix.lower() == ".zip":
        return {"content_base64": base64.b64encode(data).decode("ascii"), **options}
    return {"content": sources.decode_text(data), "name": target.name, **options}
