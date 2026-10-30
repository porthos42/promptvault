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
