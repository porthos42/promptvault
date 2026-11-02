"""Normalize and validate drafts (pipeline steps 2 and 3). Pure functions, no writes."""

from __future__ import annotations

import re

from pydantic import ValidationError

from promptvault.importers.base import PromptDraft
from promptvault.schemas import PromptCreate
from promptvault.services import categories as cat_svc
from promptvault.services import tags as tag_svc
from promptvault.services import variables as var_svc

CategoryLookup = dict[str, str]  # lookup key -> existing category slug

# License strings that mean "we do not actually know": flagged, refused unless confirmed.
UNCLEAR_LICENSES = frozenset(
    {"", "unknown", "none", "unlicensed", "no license", "n/a", "na", "noassertion", "other"}
)


def normalize_text(text: str) -> str:
    """LF line endings, no trailing spaces, at most one blank line in a row, trimmed."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _opt(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def category_lookup(session_categories: list[tuple[str, str]]) -> CategoryLookup:
    """Build the lookup from (slug, name) pairs: slug, name and slugified name all match."""
    out: CategoryLookup = {}
    for slug, name in session_categories:
        out[slug.lower()] = slug
        out[name.strip().lower()] = slug
        out.setdefault(cat_svc.slugify(name), slug)
    return out


def normalize(draft: PromptDraft, categories: CategoryLookup) -> PromptDraft:
    """Clean a draft in place and return it. Categories are mapped, never created."""
    draft.title = " ".join(draft.title.split())
    draft.body = normalize_text(draft.body)
    draft.description = normalize_text(draft.description)
    draft.model_hints = _opt(draft.model_hints)
    draft.output_format = _opt(draft.output_format)
    draft.disclaimer = _opt(draft.disclaimer)
    draft.source_url = _opt(draft.source_url)
    draft.license = _opt(draft.license)
    draft.difficulty = (_opt(draft.difficulty) or "").lower() or None
    draft.prompt_type = (_opt(draft.prompt_type) or "").lower() or None

    tags: dict[str, None] = {}
    for t in draft.tags:
        norm = tag_svc.normalize(str(t))
        if norm:
            tags.setdefault(norm, None)
    draft.tags = list(tags)

    wanted = _opt(draft.category)
    draft.category = None
    if wanted:
        slug = categories.get(wanted.lower()) or categories.get(cat_svc.slugify(wanted))
        if slug:
            draft.category = slug
        else:
            draft.warnings.append(f"category '{wanted}' does not exist; imported uncategorised")

    draft.variables = var_svc.detect(draft.body)
    return draft


def validate(draft: PromptDraft) -> PromptDraft:
    """Append per-field errors using the same limits as the prompt API."""
    fields = {
        "title": draft.title,
        "body": draft.body,
        "description": draft.description,
        "tags": draft.tags,
        "model_hints": draft.model_hints,
        "output_format": draft.output_format,
        "difficulty": draft.difficulty,
        "prompt_type": draft.prompt_type,
        "disclaimer": draft.disclaimer,
        "source_url": draft.source_url,
        "license": draft.license,
    }
    try:
        PromptCreate(**{k: v for k, v in fields.items() if v is not None})
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            draft.errors.append(f"{loc}: {err['msg']}")
    if len(draft.tags) > tag_svc.MAX_TAGS:
        draft.errors.append(f"tags: at most {tag_svc.MAX_TAGS} tags per prompt")
    return draft


def needs_license_confirm(draft: PromptDraft) -> bool:
    return (draft.license or "").strip().lower() in UNCLEAR_LICENSES
