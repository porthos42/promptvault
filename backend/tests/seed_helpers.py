"""Helpers to build throwaway seed libraries for tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CATEGORIES: dict[str, Any] = {
    "min_per_category": 0,
    "groups": [{"slug": "career", "name": "Career"}],
    "categories": [
        {"slug": "resume-writing", "name": "Resume Writing", "group": "career"},
        {"slug": "legal", "name": "Legal", "group": "career"},
    ],
}

BODY = """\
You are an expert resume writer who specializes in ATS-friendly resumes.

Rewrite the bullet below for a {{job_title}} application.

Original bullet: {{bullet}}

Rules:
- Start with a strong past-tense verb.
- Do not invent facts.

Return 3 alternatives, then one sentence on which is strongest and why.
Quality check: confirm every bullet starts with a verb.
"""


def good_prompt(**over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "seed_id": "bullet-rewriter",
        "title": "Bullet Rewriter",
        "category": "resume-writing",
        "tags": ["resume", "career"],
        "difficulty": "beginner",
        "type": "template",
        "description": "Turns a vague duty into a quantified bullet.",
        "variables": [
            {"name": "job_title", "label": "Target job title", "type": "text"},
            {"name": "bullet", "label": "Original bullet", "type": "textarea"},
        ],
        "output_format": "3 alternative bullets",
        "model_hints": "Any chat model",
        "disclaimer": None,
        "license": "CC0-1.0",
        "body": BODY,
    }
    p.update(over)
    return p


def write_library(
    root: Path, prompts: list[dict[str, Any]], categories: dict[str, Any] | None = None
) -> Path:
    """Write ``seed/categories.yaml`` and one file per prompt under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "categories.yaml").write_text(
        yaml.safe_dump(categories or CATEGORIES, sort_keys=False), encoding="utf-8"
    )
    for p in prompts:
        d = root / p["category"]
        d.mkdir(exist_ok=True)
        (d / f"{p['seed_id']}.yaml").write_text(
            yaml.safe_dump(p, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    return root
