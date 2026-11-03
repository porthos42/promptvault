"""Shared helpers for importer sources: text/bytes decoding and safe ZIP reading.

Sources arrive as JSON, so files travel inside the request: text as `content`, binary data as
`content_base64`. Nothing here touches the filesystem or the database.
"""

from __future__ import annotations

import base64
import binascii
import io
import posixpath
import zipfile
from typing import Any

from promptvault.services.errors import PayloadTooLarge, ValidationFailed

MAX_PARSE_ROWS = 20_000  # hard stop inside importers; the pipeline applies the configured cap
ZIP_MAX_ENTRIES = 5_000
ZIP_MAX_TOTAL_BYTES = 20 * 1024 * 1024  # uncompressed, all members
ZIP_MAX_MEMBER_BYTES = 1024 * 1024
MARKDOWN_SUFFIXES = (".md", ".markdown", ".txt")


def decode_text(data: bytes) -> str:
    """UTF-8 (BOM tolerated); UTF-16 when a BOM says so. Anything else is an error."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("Source is not valid UTF-8 text; re-save it as UTF-8") from exc


def source_bytes(source: Any) -> bytes:
    """Raw bytes from a str, or from a dict with `content` / `content_base64`."""
    if isinstance(source, str):
        return source.encode("utf-8")
    if isinstance(source, dict):
        if isinstance(source.get("content_base64"), str):
            try:
                return base64.b64decode(source["content_base64"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValidationFailed("content_base64 is not valid base64") from exc
        if isinstance(source.get("content"), str):
            return str(source["content"]).encode("utf-8")
    raise ValidationFailed("Source needs `content` (text) or `content_base64` (file bytes)")


def source_text(source: Any) -> str:
    if isinstance(source, dict) and isinstance(source.get("content"), str):
        return str(source["content"]).removeprefix("\ufeff")
    return decode_text(source_bytes(source))


def option(source: Any, key: str) -> Any:
    return source.get(key) if isinstance(source, dict) else None


def _check_name(name: str) -> None:
    norm = name.replace("\\", "/")
    if norm.startswith("/") or ".." in posixpath.normpath(norm).split("/") or ":" in norm[:3]:
        raise ValidationFailed(f"Unsafe path in ZIP archive: {name!r}")


def check_zip(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Entries of a ZIP after safety checks (count, sizes, path traversal)."""
    infos = zf.infolist()
    if len(infos) > ZIP_MAX_ENTRIES:
        raise PayloadTooLarge(f"ZIP has {len(infos)} entries (limit {ZIP_MAX_ENTRIES})")
    if sum(i.file_size for i in infos) > ZIP_MAX_TOTAL_BYTES:
        raise PayloadTooLarge(f"ZIP expands to more than {ZIP_MAX_TOTAL_BYTES} bytes")
    for info in infos:
        _check_name(info.filename)
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValidationFailed(f"ZIP contains a symbolic link: {info.filename!r}")
    return infos


def open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValidationFailed("Source is not a valid ZIP archive") from exc
    check_zip(zf)
    return zf


def is_junk(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return any(p.startswith(".") or p == "__MACOSX" for p in parts)


def zip_files(
    data: bytes, suffixes: tuple[str, ...] = MARKDOWN_SUFFIXES
) -> list[tuple[str, bytes]]:
    """(name, raw bytes) for each matching file in a ZIP, sorted by name. Junk is skipped."""
    out: list[tuple[str, bytes]] = []
    with open_zip(data) as zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            name = info.filename
            if info.is_dir() or is_junk(name) or not name.lower().endswith(suffixes):
                continue
            with zf.open(info) as fh:
                raw = fh.read(ZIP_MAX_MEMBER_BYTES + 1)  # headers can lie about sizes
            if len(raw) > ZIP_MAX_MEMBER_BYTES:
                raise PayloadTooLarge(f"{name} is larger than {ZIP_MAX_MEMBER_BYTES} bytes")
            out.append((name, raw))
    return out
