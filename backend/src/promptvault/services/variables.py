"""`{{variable}}` placeholder detection and rendering."""

from __future__ import annotations

import re
from typing import Any

VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
VAR_TYPES = {"text", "textarea", "number", "select"}


def detect(body: str) -> list[str]:
    """Unique variable names in order of first appearance."""
    seen: dict[str, None] = {}
    for m in VAR_RE.finditer(body):
        seen.setdefault(m.group(1), None)
    return list(seen)


def merge_variables(body: str, declared: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Variables = those found in the body, enriched with any declared metadata.

    Declared entries whose name no longer appears in the body are dropped.
    """
    meta = {str(d.get("name")): d for d in (declared or [])}
    out: list[dict[str, Any]] = []
    for name in detect(body):
        d = meta.get(name, {})
        vtype = d.get("type") or "text"
        out.append(
            {
                "name": name,
                "label": d.get("label") or name.replace("_", " ").capitalize(),
                "type": vtype if vtype in VAR_TYPES else "text",
                "default": "" if d.get("default") is None else str(d.get("default")),
                "options": [str(o) for o in (d.get("options") or [])],
            }
        )
    return out


def render(
    body: str, variables: list[dict[str, Any]], values: dict[str, Any]
) -> tuple[str, list[str]]:
    """Substitute values (falling back to defaults). Returns (text, missing names).

    Placeholders with no value and no default are left in place.
    """
    defaults = {v["name"]: v.get("default", "") for v in variables}
    missing: list[str] = []

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        val = values.get(name)
        if val is None or str(val) == "":
            val = defaults.get(name) or None
        if val is None:
            if name not in missing:
                missing.append(name)
            return m.group(0)
        return str(val)

    return VAR_RE.sub(sub, body), missing
