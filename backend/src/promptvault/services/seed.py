"""Seed library: file format (docs/SPEC.md Appendix A), parsing and the idempotent loader.

Seed prompts are YAML files at ``seed/<category>/<slug>.yaml``; ``seed/categories.yaml`` declares
the category tree (groups + categories) as data. Loading is keyed by ``seed_id`` and never
overwrites a prompt the user has edited. ``Prompt.seed_hash`` stores the fingerprint of the seed
content last applied, so "edited" means "current content differs from that fingerprint".
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from promptvault.config import Settings
from promptvault.models import Category, Prompt
from promptvault.schemas import Difficulty, PromptType, VariableType
from promptvault.services import categories as cat_svc
from promptvault.services import prompts as prompt_svc
from promptvault.services import tags as tag_svc
from promptvault.services import variables as var_svc
from promptvault.services.errors import ConflictError, NotFoundError

log = logging.getLogger(__name__)

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEED_SOURCE = "seed"
CATEGORIES_FILE = "categories.yaml"


# ---- file format ---------------------------------------------------------------------------


def _slug(v: str) -> str:
    if not SLUG_RE.match(v) or len(v) > 100:
        raise ValueError("must be a lowercase slug (a-z, 0-9, hyphens), at most 100 chars")
    return v


class SeedVariable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    label: str | None = None
    type: VariableType = "text"
    default: str | int | float | None = None
    options: list[str] = Field(default_factory=list)

    def as_declared(self) -> dict[str, Any]:
        d = self.model_dump()
        d["default"] = None if self.default is None else str(self.default)
        return d


class SeedPrompt(BaseModel):
    """One seed prompt file (Appendix A). Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    seed_id: str
    title: str = Field(min_length=1)
    category: str
    tags: list[str] = Field(default_factory=list)
    difficulty: Difficulty = "beginner"
    prompt_type: PromptType = Field(default="template", alias="type")
    description: str = ""
    variables: list[SeedVariable] = Field(default_factory=list)
    output_format: str | None = None
    model_hints: str | None = None
    disclaimer: str | None = None
    license: str | None = None
    source: str | None = Field(default=None, description="Only for third-party prompts")
    source_url: str | None = None
    body: str = Field(min_length=1)

    _v_seed_id = field_validator("seed_id", "category")(_slug)

    @field_validator("body")
    @classmethod
    def _strip_body(cls, v: str) -> str:
        return v.strip()


class SeedGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    icon: str | None = None

    _v_slug = field_validator("slug")(_slug)


class SeedCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    group: str | None = None
    icon: str | None = None

    _v_slug = field_validator("slug")(_slug)


class SeedCategoryFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_per_category: int = Field(default=0, ge=0)
    groups: list[SeedGroup] = Field(default_factory=list)
    categories: list[SeedCategory] = Field(default_factory=list)


@dataclass
class SeedLibrary:
    root: Path
    categories: SeedCategoryFile = field(default_factory=SeedCategoryFile)
    prompts: list[tuple[Path, SeedPrompt]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # "path: message"

    def by_seed_id(self, seed_id: str) -> SeedPrompt | None:
        return next((p for _, p in self.prompts if p.seed_id == seed_id), None)


def _fmt_validation(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(x) for x in e['loc']) or '(file)'}: {e['msg']}" for e in exc.errors()]


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_library(root: Path) -> SeedLibrary:
    """Parse and schema-validate everything under ``root``. Problems go to ``errors``."""
    lib = SeedLibrary(root=root)
    cat_file = root / CATEGORIES_FILE
    if cat_file.is_file():
        try:
            lib.categories = SeedCategoryFile.model_validate(_read_yaml(cat_file) or {})
        except yaml.YAMLError as exc:
            lib.errors.append(f"{CATEGORIES_FILE}: invalid YAML: {exc}")
        except ValidationError as exc:
            lib.errors += [f"{CATEGORIES_FILE}: {m}" for m in _fmt_validation(exc)]
    else:
        lib.errors.append(f"{CATEGORIES_FILE}: missing")
    for path in sorted(root.glob("*/*.yaml")):
        rel = path.relative_to(root).as_posix()
        try:
            lib.prompts.append((path, SeedPrompt.model_validate(_read_yaml(path))))
        except yaml.YAMLError as exc:
            lib.errors.append(f"{rel}: invalid YAML: {exc}")
        except ValidationError as exc:
            lib.errors += [f"{rel}: {m}" for m in _fmt_validation(exc)]
    return lib


def find_seed_dir(settings: Settings) -> Path | None:
    """Explicit setting, then the bundled copy (Docker/wheel), then the repo checkout."""
    here = Path(__file__).resolve()
    candidates = [
        settings.seed_dir,
        here.parents[1] / "seed",
        here.parents[4] / "seed",
    ]
    for c in candidates:
        if c is not None and (c / CATEGORIES_FILE).is_file():
            return c
    return None


# ---- fingerprints ---------------------------------------------------------------------------


def content_hash(snap: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest()


def target_snapshot(seed: SeedPrompt) -> dict[str, Any]:
    """What ``prompt_svc.snapshot`` returns for a prompt freshly created from ``seed``."""
    return {
        "title": seed.title,
        "body": seed.body,
        "description": seed.description,
        "model_hints": seed.model_hints,
        "output_format": seed.output_format,
        "difficulty": seed.difficulty,
        "prompt_type": seed.prompt_type,
        "disclaimer": seed.disclaimer or None,
        "source": seed.source or SEED_SOURCE,
        "source_url": seed.source_url,
        "license": seed.license,
        "category": seed.category,
        "tags": sorted(tag_svc.normalize_many(seed.tags)),
        "variables": var_svc.merge_variables(seed.body, [v.as_declared() for v in seed.variables]),
    }


def _apply_data(seed: SeedPrompt) -> dict[str, Any]:
    data = target_snapshot(seed)
    data["variables"] = [v.as_declared() for v in seed.variables]
    return data


def is_modified(prompt: Prompt) -> bool:
    """True for a seeded prompt whose content differs from the seed content last applied."""
    if prompt.seed_id is None:
        return False
    return prompt.seed_hash is None or content_hash(prompt_svc.snapshot(prompt)) != prompt.seed_hash


# ---- loader ---------------------------------------------------------------------------------


@dataclass
class SeedReport:
    categories_created: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    kept_edited: int = 0  # user-edited, left alone
    kept_trashed: int = 0  # user deleted, left alone
    invalid_files: int = 0
    reset: int = 0

    def summary(self) -> str:
        return (
            ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in vars(self).items() if v)
            or "nothing to do"
        )


def sync_categories(session: Session, lib: SeedLibrary) -> int:
    """Create missing categories (groups first). Existing ones are never renamed or moved."""
    existing = {c.slug: c for c in session.scalars(select(Category))}
    created = 0
    order = 0
    for g in lib.categories.groups:
        order += 1
        if g.slug not in existing:
            existing[g.slug] = cat_svc.create_category(
                session, {"name": g.name, "slug": g.slug, "icon": g.icon, "sort_order": order}
            )
            created += 1
    for c in lib.categories.categories:
        order += 1
        if c.slug not in existing:
            existing[c.slug] = cat_svc.create_category(
                session,
                {
                    "name": c.name,
                    "slug": c.slug,
                    "parent": c.group if c.group in existing else None,
                    "icon": c.icon,
                    "sort_order": order,
                },
            )
            created += 1
    return created


def _ensure_category(session: Session, seed: SeedPrompt) -> None:
    if session.scalar(select(Category.id).where(Category.slug == seed.category)) is None:
        cat_svc.create_category(
            session, {"name": seed.category.replace("-", " ").title(), "slug": seed.category}
        )


def _apply_seed(session: Session, prompt: Prompt, seed: SeedPrompt) -> None:
    _ensure_category(session, seed)
    prompt_svc.update_prompt(session, prompt, _apply_data(seed))
    prompt.seed_hash = content_hash(prompt_svc.snapshot(prompt))
    session.flush()


def sync(session: Session, lib: SeedLibrary) -> SeedReport:
    """Idempotent: create missing prompts, upgrade untouched ones, leave user edits alone."""
    report = SeedReport(invalid_files=len(lib.errors))
    report.categories_created = sync_categories(session, lib)
    existing = {
        p.seed_id: p
        for p in session.scalars(select(Prompt).where(Prompt.seed_id.is_not(None)))
        if p.seed_id
    }
    for _, seed in lib.prompts:
        prompt = existing.get(seed.seed_id)
        if prompt is None:
            _ensure_category(session, seed)
            prompt = prompt_svc.create_prompt(session, _apply_data(seed))
            prompt.seed_id = seed.seed_id
            prompt.seed_hash = content_hash(prompt_svc.snapshot(prompt))
            session.flush()
            report.created += 1
        elif prompt.deleted_at is not None:
            report.kept_trashed += 1
        elif is_modified(prompt):
            if content_hash(prompt_svc.snapshot(prompt)) == content_hash(target_snapshot(seed)):
                prompt.seed_hash = content_hash(prompt_svc.snapshot(prompt))  # converged
                report.unchanged += 1
            else:
                report.kept_edited += 1
        elif prompt.seed_hash != content_hash(target_snapshot(seed)):
            _apply_seed(session, prompt, seed)
            report.updated += 1
        else:
            report.unchanged += 1
    session.flush()
    return report


def _require_seed(lib: SeedLibrary | None) -> SeedLibrary:
    if lib is None:
        raise NotFoundError("Seed library not found (set PV_SEED_DIR)")
    return lib


def reset_prompt(session: Session, prompt: Prompt, lib: SeedLibrary | None) -> Prompt:
    """Restore a seeded prompt to the shipped content (kept as a new revision; tags replaced)."""
    lib = _require_seed(lib)
    if prompt.seed_id is None:
        raise ConflictError("Only seeded prompts can be reset to the original")
    seed = lib.by_seed_id(prompt.seed_id)
    if seed is None:
        raise NotFoundError(
            f"The seed file for '{prompt.seed_id}' no longer ships with this version"
        )
    _apply_seed(session, prompt, seed)
    prompt.deleted_at = None
    session.flush()
    return prompt


def reset_category(session: Session, slug: str, lib: SeedLibrary | None) -> SeedReport:
    """Reset every seeded prompt of a category, restoring trashed/missing ones too."""
    lib = _require_seed(lib)
    cat_svc.get_by_slug(session, slug)  # 404 for unknown categories
    sync_categories(session, lib)
    report = SeedReport()
    existing = {
        p.seed_id: p
        for p in session.scalars(select(Prompt).where(Prompt.seed_id.is_not(None)))
        if p.seed_id
    }
    for _, seed in lib.prompts:
        if seed.category != slug:
            continue
        prompt = existing.get(seed.seed_id)
        if prompt is None:
            _ensure_category(session, seed)
            prompt = prompt_svc.create_prompt(session, _apply_data(seed))
            prompt.seed_id = seed.seed_id
            prompt.seed_hash = content_hash(prompt_svc.snapshot(prompt))
            report.created += 1
        else:
            reset_prompt(session, prompt, lib)
            report.reset += 1
    session.flush()
    return report


def sync_from_settings(session: Session, settings: Settings) -> SeedReport | None:
    """Run the loader against the configured/bundled seed dir; None if there is none."""
    root = find_seed_dir(settings)
    if root is None:
        log.info("No seed library found; skipping seed load")
        return None
    lib = load_library(root)
    for err in lib.errors:
        log.warning("Seed file skipped: %s", err)
    return sync(session, lib)


def library_from_settings(settings: Settings) -> SeedLibrary | None:
    root = find_seed_dir(settings)
    return load_library(root) if root else None
