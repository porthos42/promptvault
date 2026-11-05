"""Seed library linter (docs/SPEC.md section 3.8). Run by CI via ``tools/lint_seed.py``.

Checks, per prompt: required fields and limits, variable declarations vs ``{{placeholders}}``,
file location (``seed/<category>/<seed_id>.yaml``), licence/source, disclaimer for regulated
domains, the quality bar (role, task, constraints, output format, example or quality check) and
PII/secret scans. Across the library: duplicate ids/titles, unknown categories and the
per-category minimum.
"""

from __future__ import annotations

import ipaddress
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from promptvault.services import variables as var_svc
from promptvault.services.seed import SeedLibrary, SeedPrompt, load_library

ALLOWED_LICENSES = {"CC0-1.0", "MIT", "Apache-2.0", "CC-BY-4.0", "CC-BY-SA-4.0"}
OWN_LICENSE = "CC0-1.0"  # prompts under other licences are third-party: source + URL required
TARGET_PER_CATEGORY = 5  # the v1 minimum, reported when min_per_category is lowered below it

# Categories (and tags) whose prompts must carry a "Not professional advice" disclaimer.
DISCLAIMER_CATEGORIES = {"legal", "finance", "real-estate"}
DISCLAIMER_TAGS = {
    "legal",
    "law",
    "contract",
    "finance",
    "tax",
    "investing",
    "investment",
    "accounting",
    "mortgage",
    "medical",
    "health",
    "healthcare",
    "nutrition",
    "mental-health",
}

LIMITS = {
    "title": (3, 100),
    "description": (20, 300),
    "body": (200, 8000),
    "output_format": (5, 200),
    "model_hints": (0, 200),
    "disclaimer": (0, 400),
}
MAX_TAGS = 8
MAX_TAG_LEN = 30

ROLE_RE = re.compile(r"(?i)\b(you are|you're|act as|acting as|your role|take the role)\b")
TASK_RE = re.compile(
    r"(?i)\b(write|create|draft|analy[sz]e|review|rewrite|generate|build|design|explain|compare|"
    r"plan|diagnose|summari[sz]e|evaluate|identify|produce|convert|turn|suggest|help|simulate|"
    r"interview|ask|extract|translate|critique|improve|outline|recommend|calculate|debug|refactor|"
    r"classify|brainstorm|teach|solve|find|give|list|prepare|develop|optimi[sz]e|rate|score)\b"
)
CONSTRAINTS_RE = re.compile(
    r"(?im)^\s*(?:#+\s*)?(rules|constraints|requirements|guidelines)\b|"
    r"\b(do not|don't|never|must|avoid|only|at most|at least|no more than|under \d+)\b"
)
OUTPUT_RE = re.compile(
    r"(?i)\b(return|output|respond|response|format|deliver|provide|produce|reply|structure)\b"
)
EXAMPLE_RE = re.compile(
    r"(?i)\b(example|e\.g\.|for instance|sample|checklist|quality check|self-check|sanity check|"
    r"double-check|verify|before (?:you )?(?:answer|respond|reply|finish|return)|"
    r"confidence|flag any)\b"
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
SECRET_RES: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_\w{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}")),
    (
        "credential assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|passwd|password|token)\b\s*[:=]\s*['\"]?"
            r"[A-Za-z0-9/+_.-]{12,}"
        ),
    ),
]


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def scan_sensitive(text: str) -> list[str]:
    """Descriptions of PII/secrets found in ``text`` (placeholders and doc examples are fine)."""
    found: list[str] = []
    for m in EMAIL_RE.finditer(text):
        if m.group(1).lower() not in SAFE_EMAIL_DOMAINS:
            found.append("email address")
    if PHONE_RE.search(text):
        found.append("phone number")
    if SSN_RE.search(text):
        found.append("SSN-like number")
    for m in CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append("card number")
    for m in IPV4_RE.finditer(text):
        try:
            if ipaddress.ip_address(m.group(0)).is_global:
                found.append(f"public IP address {m.group(0)}")
        except ValueError:
            pass
    for label, rx in SECRET_RES:
        if rx.search(text):
            found.append(label)
    return found


@dataclass
class LintResult:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)  # prompts per category slug
    files: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def needs_disclaimer(seed: SeedPrompt) -> bool:
    return seed.category in DISCLAIMER_CATEGORIES or bool(DISCLAIMER_TAGS & set(seed.tags))


def lint_prompt(path: Path, seed: SeedPrompt, root: Path) -> list[str]:
    """All problems with one prompt, as ``rel/path.yaml: message``."""
    rel = path.relative_to(root).as_posix()
    errs: list[str] = []

    def err(msg: str) -> None:
        errs.append(f"{rel}: {msg}")

    if path.parent.name != seed.category:
        err(f"category '{seed.category}' does not match its folder '{path.parent.name}'")
    if path.stem != seed.seed_id:
        err(f"file name must be the seed_id ('{seed.seed_id}.yaml')")

    for fname, (lo, hi) in LIMITS.items():
        val = getattr(seed, fname)
        if val is None:
            if lo > 0:
                err(f"'{fname}' is required")
            continue
        if not lo <= len(val.strip()) <= hi:
            err(f"'{fname}' must be {lo}-{hi} characters (is {len(val.strip())})")
    if seed.disclaimer is not None and not seed.disclaimer.strip():
        err("'disclaimer' must be null or non-empty text")

    if not 1 <= len(seed.tags) <= MAX_TAGS:
        err(f"needs 1-{MAX_TAGS} tags (has {len(seed.tags)})")
    for t in seed.tags:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", t) or len(t) > MAX_TAG_LEN:
            err(f"tag '{t}' must be a lowercase slug of at most {MAX_TAG_LEN} characters")
    if len(set(seed.tags)) != len(seed.tags):
        err("duplicate tags")

    # licence and provenance
    if not seed.license:
        err("'license' is required")
    elif seed.license not in ALLOWED_LICENSES:
        allowed = ", ".join(sorted(ALLOWED_LICENSES))
        err(f"license '{seed.license}' is not allowed (one of {allowed})")
    elif seed.license != OWN_LICENSE and not (seed.source and seed.source_url):
        err(f"third-party content ({seed.license}) needs 'source' and 'source_url'")
    if (seed.source or seed.source_url) and not (seed.source and seed.source_url):
        err("'source' and 'source_url' go together")

    # variables vs placeholders
    names = [v.name for v in seed.variables]
    for n, c in Counter(names).items():
        if c > 1:
            err(f"variable '{n}' declared {c} times")
    for v in seed.variables:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v.name) or len(v.name) > 50:
            err(f"variable name '{v.name}' is not a valid identifier")
        if not v.label:
            err(f"variable '{v.name}' needs a label")
        if v.type == "select":
            if not v.options:
                err(f"select variable '{v.name}' needs options")
            elif v.default not in (None, "") and str(v.default) not in v.options:
                err(f"default of '{v.name}' is not one of its options")
        elif v.options:
            err(f"variable '{v.name}' has options but is not a select")
    detected = var_svc.detect(seed.body)
    for n in detected:
        if n not in names:
            err(f"placeholder {{{{{n}}}}} is not declared in 'variables'")
    for n in names:
        if n not in detected:
            err(f"declared variable '{n}' is not used in the body")

    # quality bar
    body = seed.body
    if not ROLE_RE.search(body):
        err("quality bar: no role (e.g. 'You are a ...')")
    if not TASK_RE.search(body):
        err("quality bar: no clear task")
    if not CONSTRAINTS_RE.search(body):
        err("quality bar: no constraints (e.g. a 'Rules:' list)")
    if not OUTPUT_RE.search(body):
        err("quality bar: body never states the output to produce")
    if not EXAMPLE_RE.search(body):
        err("quality bar: needs at least one example or quality check")

    if needs_disclaimer(seed) and not (seed.disclaimer and seed.disclaimer.strip()):
        err("legal/finance/medical-adjacent prompt needs a 'disclaimer' (Not professional advice)")

    # PII / secrets over every text field
    texts = [seed.title, seed.description, seed.body, seed.output_format, seed.model_hints]
    texts += [seed.disclaimer, seed.source, seed.source_url]
    texts += [str(v.default) for v in seed.variables if v.default is not None]
    seen: set[str] = set()
    for text in texts:
        for hit in scan_sensitive(text or ""):
            if hit not in seen:
                seen.add(hit)
                err(f"possible PII/secret: {hit}")
    return errs


def lint_library(lib: SeedLibrary, min_per_category: int | None = None) -> LintResult:
    """Lint a parsed library. ``min_per_category`` defaults to the value in categories.yaml."""
    res = LintResult(errors=list(lib.errors), files=len(lib.prompts))
    cats = lib.categories
    known = {c.slug for c in cats.categories}
    groups = {g.slug for g in cats.groups}

    for slug, n in Counter(c.slug for c in cats.categories).items():
        if n > 1:
            res.errors.append(f"categories.yaml: duplicate category '{slug}'")
    for c in cats.categories:
        if c.group and c.group not in groups:
            res.errors.append(f"categories.yaml: category '{c.slug}' has unknown group '{c.group}'")
        if c.slug in groups:
            res.errors.append(f"categories.yaml: '{c.slug}' is both a group and a category")
        if c.parent:
            if c.parent in groups:
                res.errors.append(
                    f"categories.yaml: category '{c.slug}': parent "
                    f"'{c.parent}' is a group, use 'group'"
                )
            elif c.parent not in known:
                res.errors.append(
                    f"categories.yaml: category '{c.slug}' has unknown parent '{c.parent}'"
                )
            elif c.parent == c.slug:
                res.errors.append(f"categories.yaml: category '{c.slug}' is its own parent")

    ids: dict[str, Path] = {}
    titles: dict[tuple[str, str], Path] = {}
    for path, seed in lib.prompts:
        res.errors += lint_prompt(path, seed, lib.root)
        rel = path.relative_to(lib.root).as_posix()
        if seed.category not in known:
            res.errors.append(f"{rel}: category '{seed.category}' is not in categories.yaml")
        if seed.seed_id in ids:
            res.errors.append(f"{rel}: duplicate seed_id (also {ids[seed.seed_id].name})")
        ids.setdefault(seed.seed_id, path)
        key = (seed.category, seed.title.strip().lower())
        if key in titles:
            res.errors.append(f"{rel}: duplicate title in category (also {titles[key].name})")
        titles.setdefault(key, path)
        res.counts[seed.category] = res.counts.get(seed.category, 0) + 1

    minimum = cats.min_per_category if min_per_category is None else min_per_category
    for slug in sorted(known):
        n = res.counts.get(slug, 0)
        if n < minimum:
            res.errors.append(f"category '{slug}' has {n} prompts (minimum {minimum})")
    if minimum == 0:
        short = [c for c in known if res.counts.get(c, 0) < TARGET_PER_CATEGORY]
        res.notes.append(
            f"{len(short)} of {len(known)} categories have fewer than {TARGET_PER_CATEGORY} "
            "prompts; not enforced while min_per_category is 0 in seed/categories.yaml"
        )
    return res


def lint_dir(root: Path, min_per_category: int | None = None) -> LintResult:
    return lint_library(load_library(root), min_per_category)
