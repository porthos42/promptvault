"""Seed loader: idempotency, user edits preserved, reset to original, API, CLI and start-up."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from typer.testing import CliRunner

from promptvault.cli import app as cli_app
from promptvault.config import Settings, get_settings
from promptvault.db import make_engine, make_session_factory, run_migrations
from promptvault.main import create_app
from promptvault.models import Category, Prompt, PromptRevision
from promptvault.services import prompts as prompt_svc
from promptvault.services import seed as seed_svc
from seed_helpers import good_prompt, write_library

LEGAL = good_prompt(
    seed_id="clause-explainer",
    title="Clause Explainer",
    category="legal",
    tags=["legal", "contracts"],
    disclaimer="Not professional advice.",
)


@pytest.fixture
def lib_dir(tmp_path: Path) -> Path:
    return write_library(tmp_path / "seed", [good_prompt(), LEGAL])


@pytest.fixture
def session(tmp_path: Path, lib_dir: Path) -> Any:
    url = f"sqlite:///{(tmp_path / 'db' / 'pv.db').as_posix()}"
    run_migrations(url)
    engine = make_engine(url)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


def prompt_by_seed(session: Any, seed_id: str) -> Prompt:
    p = session.scalar(select(Prompt).where(Prompt.seed_id == seed_id))
    assert p is not None
    return p


def n_revisions(session: Any, p: Prompt) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(PromptRevision).where(PromptRevision.prompt_id == p.id)
        )
    )


def test_first_load_creates_categories_and_prompts(session: Any, lib_dir: Path) -> None:
    rep = seed_svc.sync(session, seed_svc.load_library(lib_dir))
    assert (rep.created, rep.categories_created) == (2, 3)  # 1 group + 2 categories
    cats = {c.slug: c for c in session.scalars(select(Category))}
    assert cats["resume-writing"].parent_id == cats["career"].id
    p = prompt_by_seed(session, "bullet-rewriter")
    assert p.source == "seed"
    assert p.category is not None and p.category.slug == "resume-writing"
    assert [v["name"] for v in p.variables] == ["job_title", "bullet"]
    assert p.variables[0]["label"] == "Target job title"
    assert sorted(t.name for t in p.tags) == ["career", "resume"]
    assert n_revisions(session, p) == 1
    assert not seed_svc.is_modified(p)  # fingerprint matches what the loader would compute
    assert p.seed_hash == seed_svc.content_hash(seed_svc.target_snapshot(good_seed()))


def good_seed() -> seed_svc.SeedPrompt:
    return seed_svc.SeedPrompt.model_validate(good_prompt())


def test_loading_twice_changes_nothing(session: Any, lib_dir: Path) -> None:
    lib = seed_svc.load_library(lib_dir)
    seed_svc.sync(session, lib)
    p = prompt_by_seed(session, "bullet-rewriter")
    before = (p.updated_at, n_revisions(session, p))
    rep = seed_svc.sync(session, lib)
    assert (rep.created, rep.updated, rep.kept_edited, rep.categories_created) == (0, 0, 0, 0)
    assert rep.unchanged == 2
    assert (p.updated_at, n_revisions(session, p)) == before
    assert session.scalar(select(func.count()).select_from(Prompt)) == 2


def test_untouched_prompts_are_upgraded(session: Any, tmp_path: Path) -> None:
    seed_svc.sync(session, seed_svc.load_library(write_library(tmp_path / "v1", [good_prompt()])))
    p = prompt_by_seed(session, "bullet-rewriter")
    new = good_prompt(title="Bullet Rewriter v2", tags=["resume", "ats"])
    rep = seed_svc.sync(session, seed_svc.load_library(write_library(tmp_path / "v2", [new])))
    assert rep.updated == 1
    assert p.title == "Bullet Rewriter v2"
    assert sorted(t.name for t in p.tags) == ["ats", "resume"]
    assert n_revisions(session, p) == 2
    assert not seed_svc.is_modified(p)


def test_user_edits_are_never_overwritten(session: Any, tmp_path: Path) -> None:
    seed_svc.sync(session, seed_svc.load_library(write_library(tmp_path / "v1", [good_prompt()])))
    p = prompt_by_seed(session, "bullet-rewriter")
    prompt_svc.update_prompt(session, p, {"title": "My own title"})
    assert seed_svc.is_modified(p)
    new = good_prompt(title="Shipped v2")
    rep = seed_svc.sync(session, seed_svc.load_library(write_library(tmp_path / "v2", [new])))
    assert (rep.kept_edited, rep.updated) == (1, 0)
    assert p.title == "My own title"
    # still flagged as modified, so Reset to original stays available
    assert seed_svc.is_modified(p)


def test_tag_and_body_edits_count_but_favorites_do_not(session: Any, lib_dir: Path) -> None:
    seed_svc.sync(session, seed_svc.load_library(lib_dir))
    p = prompt_by_seed(session, "bullet-rewriter")
    prompt_svc.update_prompt(session, p, {"is_favorite": True, "rating": 4})
    prompt_svc.mark_used(session, p)
    assert not seed_svc.is_modified(p)
    prompt_svc.update_prompt(session, p, {"tags": ["resume"]})
    assert seed_svc.is_modified(p)


def test_edit_that_converges_with_new_seed_is_adopted(session: Any, tmp_path: Path) -> None:
    seed_svc.sync(session, seed_svc.load_library(write_library(tmp_path / "v1", [good_prompt()])))
    p = prompt_by_seed(session, "bullet-rewriter")
    prompt_svc.update_prompt(session, p, {"title": "Shipped v2"})
    new = good_prompt(title="Shipped v2")
    rep = seed_svc.sync(session, seed_svc.load_library(write_library(tmp_path / "v2", [new])))
    assert rep.unchanged == 1
    assert not seed_svc.is_modified(p)


def test_trashed_seed_prompt_is_not_resurrected(session: Any, lib_dir: Path) -> None:
    lib = seed_svc.load_library(lib_dir)
    seed_svc.sync(session, lib)
    p = prompt_by_seed(session, "bullet-rewriter")
    prompt_svc.trash_prompt(session, p)
    rep = seed_svc.sync(session, lib)
    assert rep.kept_trashed == 1
    assert p.deleted_at is not None


def test_parent_declared_subcategory_nests(session: Any, tmp_path: Path) -> None:
    cats = {
        "min_per_category": 0,
        "groups": [{"slug": "business", "name": "Business"}],
        "categories": [
            {"slug": "finance", "name": "Finance", "group": "business"},
            {"slug": "investing", "name": "Investing", "parent": "finance"},
        ],
    }
    lib_dir = write_library(
        tmp_path / "seed-nested",
        [good_prompt(category="investing")],
        categories=cats,
    )
    seed_svc.sync(session, seed_svc.load_library(lib_dir))
    parent = session.scalar(select(Category).where(Category.slug == "finance"))
    child = session.scalar(select(Category).where(Category.slug == "investing"))
    assert parent is not None and child is not None
    assert child.parent_id == parent.id


def test_unknown_parent_is_not_fatal(session: Any, tmp_path: Path) -> None:
    cats = {
        "min_per_category": 0,
        "categories": [{"slug": "orphan", "name": "Orphan", "parent": "ghost"}],
    }
    lib_dir = write_library(
        tmp_path / "seed-orphan", [good_prompt(category="orphan")], categories=cats
    )
    seed_svc.sync(session, seed_svc.load_library(lib_dir))
    child = session.scalar(select(Category).where(Category.slug == "orphan"))
    assert child is not None and child.parent_id is None


def test_existing_category_is_not_renamed_or_moved(session: Any, lib_dir: Path) -> None:
    seed_svc.sync(session, seed_svc.load_library(lib_dir))
    cat = session.scalar(select(Category).where(Category.slug == "legal"))
    cat.name = "My Legal Stuff"
    cat.parent_id = None
    session.flush()
    seed_svc.sync(session, seed_svc.load_library(lib_dir))
    assert (cat.name, cat.parent_id) == ("My Legal Stuff", None)


def test_invalid_files_are_skipped_not_fatal(session: Any, lib_dir: Path) -> None:
    (lib_dir / "legal" / "broken.yaml").write_text("seed_id: Not A Slug\n", encoding="utf-8")
    rep = seed_svc.sync(session, seed_svc.load_library(lib_dir))
    assert (rep.created, rep.invalid_files > 0) == (2, True)


def test_reset_prompt(session: Any, lib_dir: Path) -> None:
    lib = seed_svc.load_library(lib_dir)
    seed_svc.sync(session, lib)
    p = prompt_by_seed(session, "bullet-rewriter")
    prompt_svc.update_prompt(session, p, {"title": "Mine", "body": "totally different {{x}}"})
    prompt_svc.update_prompt(session, p, {"tags": ["mine"]})
    prompt_svc.trash_prompt(session, p)
    seed_svc.reset_prompt(session, p, lib)
    assert (p.title, p.deleted_at) == ("Bullet Rewriter", None)
    assert sorted(t.name for t in p.tags) == ["career", "resume"]
    assert [v["name"] for v in p.variables] == ["job_title", "bullet"]
    assert not seed_svc.is_modified(p)
    assert n_revisions(session, p) == 4  # create, 2 edits, reset (history is kept)


def test_reset_rejects_user_prompts_and_vanished_seeds(session: Any, lib_dir: Path) -> None:
    from promptvault.services.errors import ConflictError, NotFoundError

    lib = seed_svc.load_library(lib_dir)
    mine = prompt_svc.create_prompt(session, {"title": "Mine", "body": "x"})
    with pytest.raises(ConflictError):
        seed_svc.reset_prompt(session, mine, lib)
    seed_svc.sync(session, lib)
    p = prompt_by_seed(session, "bullet-rewriter")
    (lib_dir / "resume-writing" / "bullet-rewriter.yaml").unlink()
    with pytest.raises(NotFoundError):
        seed_svc.reset_prompt(session, p, seed_svc.load_library(lib_dir))
    with pytest.raises(NotFoundError):
        seed_svc.reset_prompt(session, p, None)


def test_reset_category_restores_edited_trashed_and_missing(session: Any, lib_dir: Path) -> None:
    lib = seed_svc.load_library(lib_dir)
    seed_svc.sync(session, lib)
    p = prompt_by_seed(session, "bullet-rewriter")
    other = prompt_by_seed(session, "clause-explainer")
    prompt_svc.update_prompt(session, p, {"title": "Mine"})
    prompt_svc.update_prompt(session, other, {"title": "Mine too"})
    rep = seed_svc.reset_category(session, "resume-writing", lib)
    assert rep.reset == 1
    assert p.title == "Bullet Rewriter"
    assert other.title == "Mine too"  # other categories untouched
    session.delete(p)
    session.flush()
    rep = seed_svc.reset_category(session, "resume-writing", lib)
    assert rep.created == 1


# ---- API -------------------------------------------------------------------------------------


@pytest.fixture
def seeded_client(tmp_path: Path, lib_dir: Path) -> Any:
    settings = Settings(data_dir=tmp_path / "data", seed_dir=lib_dir, seed_on_start=True)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as c:
        yield c


def find(client: TestClient, seed_id: str) -> dict[str, Any]:
    items = client.get("/api/v1/prompts", params={"limit": 50}).json()["items"]
    return next(i for i in items if i["seed_id"] == seed_id)


def test_startup_loads_seed(seeded_client: TestClient) -> None:
    items = seeded_client.get("/api/v1/prompts").json()["items"]
    assert {i["seed_id"] for i in items} == {"bullet-rewriter", "clause-explainer"}
    assert all(i["seed_modified"] is False for i in items)
    cats = {c["slug"]: c for c in seeded_client.get("/api/v1/categories").json()}
    assert cats["resume-writing"]["prompt_count"] == 1
    assert cats["resume-writing"]["parent"] == "career"
    legal = find(seeded_client, "clause-explainer")
    assert legal["disclaimer"] == "Not professional advice."


def test_startup_seed_is_idempotent_across_restarts(tmp_path: Path, lib_dir: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", seed_dir=lib_dir, seed_on_start=True)  # type: ignore[call-arg]
    for _ in range(2):
        with TestClient(create_app(settings)) as c:
            assert c.get("/api/v1/prompts").json()["total"] == 2


def test_seed_off_loads_nothing(tmp_path: Path, lib_dir: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", seed_dir=lib_dir, seed_on_start=False)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/v1/prompts").json()["total"] == 0


def test_api_reset_to_original(seeded_client: TestClient) -> None:
    p = find(seeded_client, "bullet-rewriter")
    r = seeded_client.patch(f"/api/v1/prompts/{p['id']}", json={"title": "Edited"})
    assert r.json()["seed_modified"] is True
    r = seeded_client.post(f"/api/v1/prompts/{p['id']}/reset")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["title"], body["seed_modified"], body["version"]) == ("Bullet Rewriter", False, 3)


def test_api_reset_errors(seeded_client: TestClient) -> None:
    mine = seeded_client.post("/api/v1/prompts", json={"title": "Mine", "body": "x"}).json()
    assert seeded_client.post(f"/api/v1/prompts/{mine['id']}/reset").status_code == 409
    assert seeded_client.post("/api/v1/prompts/nope/reset").status_code == 404
    assert seeded_client.post("/api/v1/categories/nope/reset-seed").status_code == 404


def test_api_reset_category(seeded_client: TestClient) -> None:
    p = find(seeded_client, "bullet-rewriter")
    seeded_client.patch(f"/api/v1/prompts/{p['id']}", json={"title": "Edited"})
    r = seeded_client.post("/api/v1/categories/resume-writing/reset-seed")
    assert r.status_code == 200, r.text
    assert r.json()["reset"] == 1
    assert find(seeded_client, "bullet-rewriter")["title"] == "Bullet Rewriter"


def test_reset_without_seed_library_is_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed_svc, "find_seed_dir", lambda settings: None)
    settings = Settings(data_dir=tmp_path / "data", seed_on_start=False)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as c:
        mine = c.post("/api/v1/prompts", json={"title": "Mine", "body": "x"}).json()
        assert c.post(f"/api/v1/prompts/{mine['id']}/reset").status_code == 404


# ---- CLI -------------------------------------------------------------------------------------

runner = CliRunner()


@pytest.fixture
def cli_env(tmp_path: Path, lib_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("PV_DATA_DIR", str(tmp_path / "cli-data"))
    monkeypatch.setenv("PV_SEED_DIR", str(lib_dir))
    monkeypatch.setenv("PV_SEED_ON_START", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_cli_seed_and_reset(cli_env: Any) -> None:
    r = runner.invoke(cli_app, ["seed"])
    assert r.exit_code == 0, r.stdout
    assert "created 2" in r.stdout
    r = runner.invoke(cli_app, ["seed"])
    assert "unchanged 2" in r.stdout and "created" not in r.stdout

    r = runner.invoke(cli_app, ["list", "--json"])
    import json

    items = json.loads(r.stdout)["items"]
    pid = next(i["id"] for i in items if i["title"] == "Bullet Rewriter")
    assert runner.invoke(cli_app, ["edit", pid, "--title", "Mine"]).exit_code == 0
    r = runner.invoke(cli_app, ["seed", "--reset", pid])
    assert r.exit_code == 0 and "Reset" in r.stdout, r.stdout
    r = runner.invoke(cli_app, ["seed", "--reset-category", "resume-writing"])
    assert r.exit_code == 0 and "reset 1" in r.stdout, r.stdout
    r = runner.invoke(cli_app, ["seed", "--reset-category", "nope"])
    assert r.exit_code == 1


def test_cli_init_seeds(cli_env: Any) -> None:
    r = runner.invoke(cli_app, ["init"])
    assert r.exit_code == 0, r.stdout
    assert "Seed library:" in r.stdout and "created 2" in r.stdout
