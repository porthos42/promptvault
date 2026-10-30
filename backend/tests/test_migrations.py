from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from promptvault.db import downgrade, make_engine, run_migrations
from promptvault.models import Category, Prompt

EXPECTED = {"category", "tag", "prompt", "prompt_tag", "prompt_revision"}


def _url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 't.db').as_posix()}"


def test_upgrade_creates_tables_and_fts(tmp_path: Path) -> None:
    url = _url(tmp_path)
    run_migrations(url)
    run_migrations(url)  # idempotent
    engine = make_engine(url)
    names = set(inspect(engine).get_table_names())
    assert names >= EXPECTED
    assert "prompt_fts" in names


def test_fts_tracks_insert_update_delete(tmp_path: Path) -> None:
    url = _url(tmp_path)
    run_migrations(url)
    engine = make_engine(url)

    def hits(term: str) -> int:
        with engine.connect() as c:
            return len(
                c.execute(
                    text(
                        "SELECT p.id FROM prompt_fts f JOIN prompt p ON p.rowid = f.rowid "
                        "WHERE prompt_fts MATCH :t"
                    ),
                    {"t": term},
                ).all()
            )

    with Session(engine) as s:
        cat = Category(slug="resume-writing", name="Resume Writing")
        p = Prompt(
            title="Resume Bullet Rewriter",
            body="Rewrite the bullet for {{job_title}}",
            category=cat,
        )
        s.add(p)
        s.commit()
        assert hits("resume") == 1
        assert hits("rewrites") == 1  # porter stemming: rewrites -> rewrit
        p.title = "Cover Letter Writer"
        s.commit()
        assert hits("resume") == 0
        assert hits("cover") == 1
        s.delete(p)
        s.commit()
        assert hits("cover") == 0


def test_downgrade_removes_everything(tmp_path: Path) -> None:
    url = _url(tmp_path)
    run_migrations(url)
    downgrade(url, "base")
    names = set(inspect(make_engine(url)).get_table_names())
    assert not (EXPECTED & names)
    assert "prompt_fts" not in names


def test_0002_backfills_tags_text_and_search(tmp_path: Path) -> None:
    url = _url(tmp_path)
    run_migrations(url, "0001")
    engine = make_engine(url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO tag (id, name) VALUES (1, 'ats'), (2, 'career')"))
        c.execute(
            text(
                "INSERT INTO prompt (id, title, body, description, variables, created_at, updated_at) "
                "VALUES ('p1', 'Old Prompt', 'body text', '', '[]', '2026-01-01', '2026-01-01')"
            )
        )
        c.execute(text("INSERT INTO prompt_tag (prompt_id, tag_id) VALUES ('p1', 1), ('p1', 2)"))
    run_migrations(url)
    with engine.connect() as c:
        tags_text = c.execute(text("SELECT tags_text FROM prompt WHERE id='p1'")).scalar()
        assert set(str(tags_text).split()) == {"ats", "career"}
        hit = c.execute(text("SELECT count(*) FROM prompt_fts WHERE prompt_fts MATCH 'career'"))
        assert hit.scalar() == 1  # existing rows are indexed after upgrade
        vocab = {r[0] for r in c.execute(text("SELECT term FROM prompt_terms_vocab"))}
        assert {"old", "prompt", "career"} <= vocab


def test_use_count_updates_do_not_reindex(tmp_path: Path) -> None:
    url = _url(tmp_path)
    run_migrations(url)
    engine = make_engine(url)
    with Session(engine) as s:
        p = Prompt(title="Alpha", body="beta gamma")
        s.add(p)
        s.commit()
        p.use_count = 5
        s.commit()
        with engine.connect() as c:
            n = c.execute(text("SELECT count(*) FROM prompt_fts WHERE prompt_fts MATCH 'beta'"))
            assert n.scalar() == 1
