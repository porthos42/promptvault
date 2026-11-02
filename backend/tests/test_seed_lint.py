"""Seed linter: good and bad fixtures, plus the real seed/ folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from promptvault.services.seedlint import lint_dir, scan_sensitive
from seed_helpers import CATEGORIES, good_prompt, write_library

REPO_SEED = Path(__file__).resolve().parents[2] / "seed"


def errors(tmp_path: Path, prompts: list[dict[str, Any]], **kw: Any) -> list[str]:
    return lint_dir(write_library(tmp_path / "seed", prompts), **kw).errors


def test_repo_seed_library_is_clean() -> None:
    res = lint_dir(REPO_SEED)
    assert res.errors == []
    assert res.files >= 3


def test_good_fixture_passes(tmp_path: Path) -> None:
    assert errors(tmp_path, [good_prompt()]) == []


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"license": None}, "'license' is required"),
        ({"license": "GPL-3.0"}, "not allowed"),
        ({"license": "MIT"}, "needs 'source' and 'source_url'"),
        ({"source": "Some blog"}, "go together"),
        ({"tags": []}, "needs 1-8 tags"),
        ({"tags": ["Bad Tag"]}, "lowercase slug"),
        ({"description": "short"}, "'description' must be"),
        ({"title": "x" * 101}, "'title' must be"),
        ({"output_format": None}, "'output_format' is required"),
        ({"disclaimer": "  "}, "non-empty"),
        ({"category": "legal"}, "does not match its folder"),
        ({"seed_id": "other-id"}, "file name must be the seed_id"),
    ],
)
def test_bad_fields(tmp_path: Path, override: dict[str, Any], expected: str) -> None:
    root = write_library(tmp_path / "seed", [good_prompt()])
    # rewrite the single file with the override, keeping the original location
    import yaml

    path = root / "resume-writing" / "bullet-rewriter.yaml"
    path.write_text(yaml.safe_dump(good_prompt(**override), sort_keys=False), encoding="utf-8")
    assert any(expected in e for e in lint_dir(root).errors), lint_dir(root).errors


def test_missing_required_field_is_a_schema_error(tmp_path: Path) -> None:
    p = good_prompt()
    del p["body"]
    errs = errors(tmp_path, [p])
    assert any("body" in e and "required" in e.lower() for e in errs)


def test_unknown_key_rejected(tmp_path: Path) -> None:
    errs = errors(tmp_path, [good_prompt(surprise=1)])
    assert any("surprise" in e for e in errs)


def test_variables_must_match_body(tmp_path: Path) -> None:
    undeclared = good_prompt(variables=[{"name": "job_title", "label": "Job"}])
    assert any("{{bullet}} is not declared" in e for e in errors(tmp_path / "a", [undeclared]))
    extra = good_prompt(
        variables=good_prompt()["variables"] + [{"name": "unused", "label": "Unused"}]
    )
    assert any("'unused' is not used" in e for e in errors(tmp_path / "b", [extra]))
    dup = good_prompt(variables=good_prompt()["variables"] * 2)
    assert any("declared 2 times" in e for e in errors(tmp_path / "c", [dup]))
    nolabel = good_prompt(variables=[{"name": "job_title"}, {"name": "bullet", "label": "B"}])
    assert any("needs a label" in e for e in errors(tmp_path / "d", [nolabel]))


def test_select_variable_rules(tmp_path: Path) -> None:
    body = good_prompt()["body"] + "Tone: {{tone}}\n"
    base = good_prompt()["variables"]
    no_opts = good_prompt(
        body=body, variables=base + [{"name": "tone", "label": "T", "type": "select"}]
    )
    assert any("needs options" in e for e in errors(tmp_path / "a", [no_opts]))
    bad_default = good_prompt(
        body=body,
        variables=base
        + [{"name": "tone", "label": "T", "type": "select", "options": ["a", "b"], "default": "c"}],
    )
    assert any("not one of its options" in e for e in errors(tmp_path / "b", [bad_default]))
    ok = good_prompt(
        body=body,
        variables=base
        + [{"name": "tone", "label": "T", "type": "select", "options": ["a", "b"], "default": "a"}],
    )
    assert errors(tmp_path / "c", [ok]) == []


def test_duplicate_seed_ids_and_titles(tmp_path: Path) -> None:
    root = write_library(tmp_path / "seed", [good_prompt()])
    import yaml

    # same seed_id in another category folder, and same title in the same category
    (root / "legal").mkdir()
    (root / "legal" / "bullet-rewriter.yaml").write_text(
        yaml.safe_dump(
            good_prompt(category="legal", disclaimer="Not professional advice."), sort_keys=False
        ),
        encoding="utf-8",
    )
    (root / "resume-writing" / "second.yaml").write_text(
        yaml.safe_dump(good_prompt(seed_id="second"), sort_keys=False), encoding="utf-8"
    )
    errs = lint_dir(root).errors
    assert any("duplicate seed_id" in e for e in errs)
    assert any("duplicate title in category" in e for e in errs)


def test_unknown_category(tmp_path: Path) -> None:
    errs = errors(tmp_path, [good_prompt(category="nope")])
    assert any("not in categories.yaml" in e for e in errs)


@pytest.mark.parametrize(
    ("body_change", "expected"),
    [
        (
            ("You are an expert resume writer who specializes in ATS-friendly resumes.\n", ""),
            "no role",
        ),
        (
            ("Rules:\n- Start with a strong past-tense verb.\n- Do not invent facts.\n", ""),
            "no constraints",
        ),
        (
            ("Return 3 alternatives, then one sentence on which is strongest and why.\n", ""),
            "output",
        ),
        (
            ("Quality check: confirm every bullet starts with a verb.\n", ""),
            "example or quality check",
        ),
    ],
)
def test_quality_bar(tmp_path: Path, body_change: tuple[str, str], expected: str) -> None:
    body = good_prompt()["body"].replace(*body_change)
    assert body != good_prompt()["body"]
    errs = errors(tmp_path, [good_prompt(body=body)])
    assert any("quality bar" in e and expected in e for e in errs), errs


def test_body_length_limits(tmp_path: Path) -> None:
    assert any(
        "'body' must be" in e for e in errors(tmp_path / "a", [good_prompt(body="You are x.")])
    )
    long_body = good_prompt()["body"] + "x" * 8000
    assert any(
        "'body' must be" in e
        for e in errors(tmp_path / "b", [long_body and good_prompt(body=long_body)])
    )


def test_disclaimer_required_for_regulated_domains(tmp_path: Path) -> None:
    legal = good_prompt(seed_id="clause", title="Clause", category="legal")
    assert any("needs a 'disclaimer'" in e for e in errors(tmp_path / "a", [legal]))
    ok = good_prompt(
        seed_id="clause", title="Clause", category="legal", disclaimer="Not professional advice."
    )
    assert errors(tmp_path / "b", [ok]) == []
    # a medical-adjacent tag triggers it in any category
    tagged = good_prompt(tags=["resume", "health"])
    assert any("needs a 'disclaimer'" in e for e in errors(tmp_path / "c", [tagged]))


AT = "@"
DOT = "."
SENSITIVE = [
    "Contact jane" + AT + "acme" + DOT + "io for details",
    "Call 415-555-" + "0132 today",
    "SSN 123-45-" + "6789",
    "Card 4111 1111 1111 " + "1111",
    "Server at 8" + DOT + "8" + DOT + "8" + DOT + "8",
    "key sk-" + "abcdefghijklmnopqrstuvwx",
    "token ghp_" + "a" * 36,
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "api_key = abcdef1234567890",
    "-----BEGIN RSA PRIVATE KEY-----",
]
ALLOWED = [
    "Email {{email}} or name" + AT + "example" + DOT + "com",
    "Router at 192" + DOT + "168" + DOT + "1" + DOT + "1, 10" + DOT + "0" + DOT + "0" + DOT + "5",
    "Doc range 203" + DOT + "0" + DOT + "113" + DOT + "7",
    "Order 4111 1111 1111 " + "1112 is not a valid card",
    "Set password: {{password}}",
    "Use 3 bullets, each under 25 words, in 2026",
]


@pytest.mark.parametrize("text", SENSITIVE)
def test_scan_flags_sensitive(text: str) -> None:
    assert scan_sensitive(text)


@pytest.mark.parametrize("text", ALLOWED)
def test_scan_allows_placeholders_and_docs(text: str) -> None:
    assert scan_sensitive(text) == []


def test_pii_in_body_fails_lint(tmp_path: Path) -> None:
    body = good_prompt()["body"] + "Reach me at jane" + AT + "acme" + DOT + "io\n"
    assert any(
        "possible PII/secret: email" in e for e in errors(tmp_path, [good_prompt(body=body)])
    )


def test_min_per_category(tmp_path: Path) -> None:
    root = write_library(tmp_path / "seed", [good_prompt()])
    assert lint_dir(root).ok  # categories.yaml says 0
    res = lint_dir(root, min_per_category=2)
    assert any("'resume-writing' has 1 prompts (minimum 2)" in e for e in res.errors)
    assert any("'legal' has 0 prompts" in e for e in res.errors)
    assert lint_dir(root, min_per_category=1).errors == [
        "category 'legal' has 0 prompts (minimum 1)"
    ]


def test_min_per_category_from_categories_file(tmp_path: Path) -> None:
    cats = {**CATEGORIES, "min_per_category": 1}
    root = write_library(tmp_path / "seed", [good_prompt()], categories=cats)
    assert [e for e in lint_dir(root).errors if "minimum" in e] == [
        "category 'legal' has 0 prompts (minimum 1)"
    ]


def test_categories_file_checks(tmp_path: Path) -> None:
    cats = {
        "groups": [{"slug": "career", "name": "Career"}],
        "categories": [
            {"slug": "a", "name": "A", "group": "missing"},
            {"slug": "a", "name": "A again"},
            {"slug": "career", "name": "Clash"},
        ],
    }
    root = write_library(tmp_path / "seed", [], categories=cats)
    errs = "\n".join(lint_dir(root).errors)
    assert "unknown group 'missing'" in errs
    assert "duplicate category 'a'" in errs
    assert "both a group and a category" in errs


def test_invalid_yaml_and_missing_categories_file(tmp_path: Path) -> None:
    root = tmp_path / "seed"
    (root / "x").mkdir(parents=True)
    (root / "x" / "broken.yaml").write_text("a: [unclosed", encoding="utf-8")
    errs = lint_dir(root).errors
    assert any("categories.yaml: missing" in e for e in errs)
    assert any("broken.yaml" in e and "invalid YAML" in e for e in errs)
