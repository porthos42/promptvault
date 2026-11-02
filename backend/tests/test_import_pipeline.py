"""Importer framework units: normalize, validate, dedupe, registry, commit actions, license gate."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from promptvault import importers
from promptvault.db import make_engine, make_session_factory, run_migrations
from promptvault.importers import dedupe, jobs, normalize, pipeline
from promptvault.importers.base import ImporterRegistry, PromptDraft
from promptvault.models import Category, ImportJob, Prompt
from promptvault.services import prompts as svc
from promptvault.services.errors import NotFoundError, PayloadTooLarge, ValidationFailed

EDITOR = (
    "Review the following draft and point out unclear sentences, passive voice and weak verbs. "
    "Suggest a rewrite for each problem and explain why the change helps the reader. "
    "Keep the original meaning and the author's tone."
)
EDITOR_NEAR = EDITOR.replace("unclear", "unclean")  # one word off: fuzzy, not exact
SQL = "Write a SQL query that returns the ten customers with the highest revenue in each region."


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    url = f"sqlite:///{(tmp_path / 'u.db').as_posix()}"
    run_migrations(url)
    engine = make_engine(url)
    with make_session_factory(engine)() as s:
        s.add(Category(slug="writing", name="Writing & Editing"))
        s.commit()
        yield s
    engine.dispose()


def row(title: str, body: str, **extra: Any) -> dict[str, Any]:
    return {"title": title, "body": body, "license": "MIT", **extra}


def analyze(session: Session, rows: list[dict[str, Any]]) -> list[pipeline.Row]:
    return pipeline.analyze(session, "passthrough", rows, 100)


def run(session: Session, rows: list[dict[str, Any]], **opts: Any) -> list[dict[str, Any]]:
    planned = pipeline.plan(analyze(session, rows), pipeline.CommitOptions(**opts))
    pipeline.execute(session, "passthrough", planned)
    session.commit()
    return planned


def count(session: Session, *where: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(Prompt).where(*where)) or 0)


# ---- normalize / validate ----------------------------------------------------------------


def test_normalize_cleans_text_tags_and_category() -> None:
    cats = normalize.category_lookup([("writing", "Writing & Editing")])
    d = PromptDraft(
        title="  Hello \n  World ",
        body="line one  \r\n\r\n\r\n\r\nline two {{name}}\r\n",
        tags=["Resume ", "ATS", "resume", "  ", "Cover Letter"],
        category="Writing & Editing",
        difficulty=" Advanced ",
        license="  ",
        model_hints="",
    )
    normalize.normalize(d, cats)
    assert d.title == "Hello World"
    assert d.body == "line one\n\nline two {{name}}"
    assert d.tags == ["resume", "ats", "cover-letter"]
    assert d.category == "writing"
    assert d.difficulty == "advanced"
    assert d.license is None and d.model_hints is None
    assert d.variables == ["name"]
    assert d.warnings == []


def test_unknown_category_is_dropped_with_a_warning_never_created(session: Session) -> None:
    rows = analyze(session, [row("A", SQL, category="Nonexistent")])
    assert rows[0].draft.category is None
    assert "does not exist" in rows[0].draft.warnings[0]
    run(session, [row("A", SQL, category="Nonexistent")])
    assert session.scalar(select(func.count()).select_from(Category)) == 1


def test_validate_reports_per_row_errors_and_good_rows_survive(session: Session) -> None:
    rows = analyze(
        session,
        [
            row("Good", SQL),
            row("", "has no title"),
            row("Bad difficulty", "x", difficulty="expert"),
            row("t" * 301, "too long title"),
            {"title": "Many", "body": "b", "tags": [f"t{i}" for i in range(31)]},
            "not an object",
        ],
    )
    assert [r.status for r in rows] == [
        "new",
        "invalid",
        "invalid",
        "invalid",
        "invalid",
        "invalid",
    ]
    assert any(e.startswith("title") for e in rows[1].draft.errors)
    assert any(e.startswith("difficulty") for e in rows[2].draft.errors)
    assert any("tags" in e for e in rows[4].draft.errors)
    assert rows[5].draft.errors == ["row is not an object"]


def test_needs_license_confirm_rules() -> None:
    for lic, expected in [
        (None, True),
        ("", True),
        ("Unknown", True),
        ("NOASSERTION", True),
        ("MIT", False),
        ("CC-BY-4.0", False),
    ]:
        assert normalize.needs_license_confirm(PromptDraft(license=lic)) is expected


# ---- dedupe ------------------------------------------------------------------------------


def test_similarity_threshold_and_prefilters() -> None:
    a, b = dedupe.compare_text(EDITOR), dedupe.compare_text(EDITOR_NEAR)
    assert dedupe.FUZZY_THRESHOLD == 0.92
    assert dedupe.similarity(a, a) == 1.0
    assert dedupe.similarity(a, b) >= dedupe.FUZZY_THRESHOLD
    assert dedupe.similarity(a, dedupe.compare_text(SQL)) == 0.0
    assert dedupe.similarity(a, a[: len(a) // 2]) == 0.0  # length-ratio prefilter
    assert dedupe.similarity("", "") == 1.0 and dedupe.similarity("", "x") == 0.0


def test_exact_and_fuzzy_dedupe_against_existing_prompts(session: Session) -> None:
    existing = svc.create_prompt(session, {"title": "Editor", "body": EDITOR})
    session.commit()
    rows = analyze(
        session,
        [
            row("Same body, other whitespace", EDITOR.replace(" and ", "  and\n")),
            row("Near copy", EDITOR_NEAR),
            row("Unrelated", SQL),
        ],
    )
    assert [r.status for r in rows] == ["duplicate", "duplicate", "new"]
    assert (
        rows[0].match and rows[0].match.kind == "exact" and rows[0].match.prompt_id == existing.id
    )
    assert rows[1].match and rows[1].match.kind == "fuzzy" and rows[1].match.score >= 0.92
    assert rows[2].match is None


def test_dedupe_within_a_batch(session: Session) -> None:
    rows = analyze(session, [row("One", EDITOR), row("Two", EDITOR), row("Three", EDITOR_NEAR)])
    assert [r.status for r in rows] == ["new", "duplicate", "duplicate"]
    assert rows[1].match is not None and rows[1].match.batch_index == 0
    assert rows[1].match.kind == "exact" and rows[1].match.prompt_id is None
    assert rows[2].match is not None and rows[2].match.kind == "fuzzy"
    assert rows[2].match.batch_index == 0


def test_invalid_rows_do_not_take_part_in_dedupe(session: Session) -> None:
    rows = analyze(session, [row("", EDITOR), row("Valid", EDITOR)])
    assert [r.status for r in rows] == ["invalid", "new"]


def test_trashed_prompts_are_never_matched(session: Session) -> None:
    gone = svc.create_prompt(session, {"title": "Gone", "body": EDITOR})
    svc.trash_prompt(session, gone)
    session.commit()
    rows = analyze(session, [row("Again", EDITOR), row("Near", EDITOR_NEAR)])
    assert [r.status for r in rows] == ["new", "duplicate"]  # row 1 matches row 0, not the trash
    assert rows[0].match is None and "trashed prompt" in rows[0].draft.warnings[0]
    assert rows[1].match is not None and rows[1].match.prompt_id is None


# ---- registry ----------------------------------------------------------------------------


class Fixed:
    name = "fixed"

    def parse(self, source: Any) -> list[PromptDraft]:
        return [PromptDraft(title="T", body=str(source))]


def test_registry_register_get_list() -> None:
    reg = ImporterRegistry()
    reg.register(Fixed())
    assert reg.names() == ["fixed"]
    assert reg.get("fixed").parse("b")[0].body == "b"
    with pytest.raises(ValueError):
        reg.register(Fixed())
    reg.register(Fixed(), replace=True)
    with pytest.raises(NotFoundError):
        reg.get("nope")
    with pytest.raises(ValueError):
        reg.register(type("Bad", (), {"name": "bad name!", "parse": lambda s, x: []})())
    reg.unregister("fixed")
    assert reg.names() == []


def test_passthrough_is_registered_and_custom_importers_plug_in(session: Session) -> None:
    assert "passthrough" in importers.names()
    importers.register(Fixed(), replace=True)
    try:
        rows = pipeline.analyze(session, "fixed", "Body from a plugin", 10)
        assert rows[0].draft.body == "Body from a plugin"
    finally:
        importers.registry.unregister("fixed")


def test_parse_failures_and_row_cap(session: Session) -> None:
    with pytest.raises(ValidationFailed):
        pipeline.analyze(session, "passthrough", {"nope": 1}, 10)
    with pytest.raises(PayloadTooLarge):
        pipeline.analyze(session, "passthrough", [row(f"T{i}", f"body {i}") for i in range(4)], 3)
    with pytest.raises(NotFoundError):
        pipeline.analyze(session, "missing", [], 10)


# ---- commit ------------------------------------------------------------------------------


def test_commit_creates_prompts_with_provenance(session: Session) -> None:
    planned = run(
        session,
        [
            row(
                "Editor",
                EDITOR,
                category="writing",
                tags=["Edit", "style"],
                source_url="https://example.com/p/1",
                license="CC-BY-4.0",
                difficulty="advanced",
            )
        ],
    )
    assert planned[0]["outcome"] == "created"
    p = svc.get_prompt(session, planned[0]["prompt_id"])
    assert (p.source, p.source_url, p.license) == (
        "import:passthrough",
        "https://example.com/p/1",
        "CC-BY-4.0",
    )
    assert p.category is not None and p.category.slug == "writing"
    assert sorted(t.name for t in p.tags) == ["edit", "style"]
    assert p.difficulty == "advanced"
    assert svc.current_version(session, p.id) == 1


def test_duplicate_default_is_skip(session: Session) -> None:
    svc.create_prompt(session, {"title": "Editor", "body": EDITOR})
    session.commit()
    planned = run(session, [row("Dup", EDITOR), row("New", SQL)])
    assert [r["outcome"] for r in planned] == ["skipped", "created"]
    assert count(session) == 2


def test_replace_goes_through_update_path_and_keeps_revision(session: Session) -> None:
    old = svc.create_prompt(
        session, {"title": "Old title", "body": EDITOR, "description": "keep me", "tags": ["a"]}
    )
    session.commit()
    planned = run(
        session,
        [row("New title", EDITOR_NEAR, source_url="https://x.test/1")],
        default_action="replace",
    )
    assert planned[0]["outcome"] == "replaced" and planned[0]["prompt_id"] == old.id
    session.expire_all()
    p = svc.get_prompt(session, old.id)
    assert (p.title, p.body) == ("New title", EDITOR_NEAR)
    assert p.description == "keep me"  # draft gave none, so the existing value is kept
    assert [t.name for t in p.tags] == ["a"]
    assert (p.source, p.source_url) == ("import:passthrough", "https://x.test/1")
    revs = svc.list_revisions(session, p)
    assert [r.version for r in revs] == [2, 1]
    assert revs[1].snapshot["title"] == "Old title" and revs[1].snapshot["body"] == EDITOR
    assert count(session) == 1


def test_keep_both_creates_a_second_prompt(session: Session) -> None:
    svc.create_prompt(session, {"title": "Editor", "body": EDITOR})
    session.commit()
    planned = run(session, [row("Editor copy", EDITOR)], default_action="keep_both")
    assert planned[0]["outcome"] == "created"
    assert count(session) == 2


def test_per_row_actions_override_the_default(session: Session) -> None:
    svc.create_prompt(session, {"title": "Editor", "body": EDITOR})
    svc.create_prompt(session, {"title": "SQL", "body": SQL})
    session.commit()
    planned = run(
        session,
        [row("E2", EDITOR), row("S2", SQL)],
        default_action="skip",
        actions={1: "keep_both"},
    )
    assert [r["outcome"] for r in planned] == ["skipped", "created"]


def test_batch_duplicate_cannot_be_replaced(session: Session) -> None:
    rows = analyze(session, [row("One", EDITOR), row("Two", EDITOR)])
    with pytest.raises(ValidationFailed, match="earlier row"):
        pipeline.plan(rows, pipeline.CommitOptions(actions={1: "replace"}))
    planned = pipeline.plan(rows, pipeline.CommitOptions(default_action="replace"))
    assert planned[1]["action"] == "skip"  # a global default degrades to skip
    with pytest.raises(ValidationFailed, match="does not exist"):
        pipeline.plan(rows, pipeline.CommitOptions(actions={9: "skip"}))


def test_trashed_prompts_stay_untouched_and_are_not_replaced(session: Session) -> None:
    gone = svc.create_prompt(session, {"title": "Gone", "body": EDITOR})
    svc.trash_prompt(session, gone)
    session.commit()
    deleted_at = gone.deleted_at
    planned = run(session, [row("Fresh", EDITOR)], default_action="replace")
    assert planned[0]["outcome"] == "created"
    session.expire_all()
    still = svc.get_prompt(session, gone.id)
    assert still.deleted_at == deleted_at and still.title == "Gone"
    assert count(session, Prompt.deleted_at.is_(None)) == 1


def test_replace_target_trashed_after_preview_is_skipped(session: Session) -> None:
    target = svc.create_prompt(session, {"title": "T", "body": EDITOR})
    session.commit()
    planned = pipeline.plan(
        analyze(session, [row("New", EDITOR)]), pipeline.CommitOptions(default_action="replace")
    )
    svc.trash_prompt(session, target)
    session.commit()
    pipeline.execute(session, "passthrough", planned)
    assert planned[0]["outcome"] == "skipped" and "trashed" in planned[0]["reason"]
    assert svc.get_prompt(session, target.id).title == "T"


def test_invalid_rows_never_block_good_rows(session: Session) -> None:
    planned = run(session, [row("", "no title"), row("Good", SQL)])
    assert [r["outcome"] for r in planned] == ["invalid", "created"]


# ---- license gate ------------------------------------------------------------------------


def test_unclear_license_rows_are_refused_unless_confirmed(session: Session) -> None:
    rows = [
        {"title": "No license", "body": EDITOR},
        {"title": "Unknown", "body": SQL, "license": "unknown"},
        row("Licensed", "A third, unrelated body about gardening tomatoes in raised beds."),
    ]
    assert [r.needs_license_confirm for r in analyze(session, rows)] == [True, True, False]
    planned = run(session, rows)
    assert [r["outcome"] for r in planned] == ["refused", "refused", "created"]
    assert "confirm" in planned[0]["reason"]
    assert count(session) == 1

    planned = run(session, rows, confirmed_rows=frozenset({0}))  # only row 0 confirmed
    assert [r["outcome"] for r in planned] == ["created", "refused", "skipped"]
    planned = run(session, rows, confirm_license=True)
    assert [r["outcome"] for r in planned] == ["skipped", "created", "skipped"]
    assert count(session) == 3
    assert svc.get_prompt(session, planned[1]["prompt_id"]).license == "unknown"


def test_skipped_duplicates_are_not_refused_for_license(session: Session) -> None:
    svc.create_prompt(session, {"title": "Editor", "body": EDITOR})
    session.commit()
    planned = run(session, [{"title": "Dup", "body": EDITOR}])
    assert planned[0]["outcome"] == "skipped"


# ---- jobs --------------------------------------------------------------------------------


def test_job_runner_counts_persists_and_recovers(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'j.db').as_posix()}"
    run_migrations(url)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    runner = jobs.JobRunner(factory)
    try:
        with factory() as s:
            rows = pipeline.plan(
                pipeline.analyze(
                    s,
                    "passthrough",
                    [row("A", EDITOR), {"title": "B", "body": SQL}, row("", "x")],
                    9,
                ),
                pipeline.CommitOptions(),
            )
            job = jobs.create_job(s, "passthrough", rows)
            s.commit()
            runner.run_now(s, job.id)
        view = runner.view(job.id, results=True)
        assert view["status"] == "done"
        assert (view["total"], view["processed"], view["created"]) == (3, 3, 1)
        assert (view["refused"], view["invalid"]) == (1, 1)
        assert [r["outcome"] for r in view["results"]] == ["created", "refused", "invalid"]

        with factory() as s:
            stuck = ImportJob(importer="passthrough", status="running", drafts=[])
            s.add(stuck)
            s.commit()
            assert jobs.fail_interrupted(s) == 1
            s.commit()
            assert runner.view(stuck.id)["status"] == "failed"
        with pytest.raises(NotFoundError):
            runner.view("missing")
    finally:
        runner.shutdown()
        engine.dispose()


def test_job_failure_rolls_back_every_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite:///{(tmp_path / 'f.db').as_posix()}"
    run_migrations(url)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    runner = jobs.JobRunner(factory)
    real = svc.create_prompt
    calls = {"n": 0}

    def flaky(session: Session, data: dict[str, Any]) -> Prompt:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk on fire")
        return real(session, data)

    monkeypatch.setattr(svc, "create_prompt", flaky)
    try:
        with factory() as s:
            rows = pipeline.plan(
                pipeline.analyze(s, "passthrough", [row("A", EDITOR), row("B", SQL)], 9),
                pipeline.CommitOptions(),
            )
            job = jobs.create_job(s, "passthrough", rows)
            s.commit()
            runner.run_now(s, job.id)
            assert count(s) == 0  # first row was rolled back with the rest
        view = runner.view(job.id)
        assert view["status"] == "failed" and "disk on fire" in view["error"]
        assert view["created"] == 0
    finally:
        runner.shutdown()
        engine.dispose()
