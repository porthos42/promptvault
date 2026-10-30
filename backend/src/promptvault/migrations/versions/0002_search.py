"""search: tags_text + last_used_at columns, FTS5 index (live prompts only) with tags, term index

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_OLD_COLS = "title, description, body"
_NEW_COLS = "title, description, body, tags_text"


def _drop_fts() -> None:
    for trg in (
        "prompt_fts_ai",
        "prompt_fts_ad",
        "prompt_fts_au",
        "prompt_fts_au_trash",
        "prompt_fts_au_restore",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trg}")
    op.execute("DROP TABLE IF EXISTS prompt_terms_vocab")
    op.execute("DROP TABLE IF EXISTS prompt_terms")
    op.execute("DROP TABLE IF EXISTS prompt_fts")


def _create_fts(cols: str, with_terms: bool, live_only: bool) -> None:
    """Create the FTS5 index (+ optional unstemmed term index) and its sync triggers.

    With live_only=True, trashed prompts (deleted_at set) are kept out of the index, so searches
    never need to filter them. External-content 'delete' must only be issued for rows that are
    actually indexed, hence the WHEN clauses.
    """
    names = [c.strip() for c in cols.split(",")]
    new_vals = ", ".join(f"new.{c}" for c in names)
    old_vals = ", ".join(f"old.{c}" for c in names)
    indexes = ["prompt_fts"] + (["prompt_terms"] if with_terms else [])
    live = "deleted_at IS NULL"

    op.execute(
        f"CREATE VIRTUAL TABLE prompt_fts USING fts5({cols}, content='prompt', "
        "content_rowid='rowid', tokenize='porter unicode61')"
    )
    if with_terms:
        # Unstemmed copy of the text: its vocabulary gives real words for typo correction.
        op.execute(
            f"CREATE VIRTUAL TABLE prompt_terms USING fts5({cols}, content='prompt', "
            "content_rowid='rowid', tokenize='unicode61')"
        )
        op.execute("CREATE VIRTUAL TABLE prompt_terms_vocab USING fts5vocab('prompt_terms', 'row')")
    where = f" WHERE {live}" if live_only else ""
    for ix in indexes:
        op.execute(f"INSERT INTO {ix}(rowid, {cols}) SELECT rowid, {cols} FROM prompt{where}")

    ins = "; ".join(
        f"INSERT INTO {ix}(rowid, {cols}) VALUES (new.rowid, {new_vals})" for ix in indexes
    )
    dele = "; ".join(
        f"INSERT INTO {ix}({ix}, rowid, {cols}) VALUES ('delete', old.rowid, {old_vals})"
        for ix in indexes
    )

    def trigger(name: str, event: str, when: str, body: str) -> None:
        w = f" WHEN {when}" if when else ""
        op.execute(f"CREATE TRIGGER {name} AFTER {event} ON prompt{w} BEGIN {body}; END")

    if not live_only:
        trigger("prompt_fts_ai", "INSERT", "", ins)
        trigger("prompt_fts_ad", "DELETE", "", dele)
        # only re-index when searchable text changes (not on use_count / favorite updates)
        trigger("prompt_fts_au", f"UPDATE OF {cols}", "", f"{dele}; {ins}")
        return
    trigger("prompt_fts_ai", "INSERT", "new.deleted_at IS NULL", ins)
    trigger("prompt_fts_ad", "DELETE", "old.deleted_at IS NULL", dele)
    # text changed while live -> re-index
    trigger(
        "prompt_fts_au",
        f"UPDATE OF {cols}",
        "old.deleted_at IS NULL AND new.deleted_at IS NULL",
        f"{dele}; {ins}",
    )
    # live -> trashed: drop from index; trashed -> live: add back
    trigger(
        "prompt_fts_au_trash",
        "UPDATE OF deleted_at",
        "old.deleted_at IS NULL AND new.deleted_at IS NOT NULL",
        dele,
    )
    trigger(
        "prompt_fts_au_restore",
        "UPDATE OF deleted_at",
        "old.deleted_at IS NOT NULL AND new.deleted_at IS NULL",
        ins,
    )


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        _drop_fts()
    op.add_column("prompt", sa.Column("tags_text", sa.Text, nullable=False, server_default=""))
    op.add_column("prompt", sa.Column("last_used_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE prompt SET tags_text = COALESCE((SELECT group_concat(t.name, ' ') "
        "FROM prompt_tag pt JOIN tag t ON t.id = pt.tag_id WHERE pt.prompt_id = prompt.id), '')"
    )
    if sqlite:
        _create_fts(_NEW_COLS, with_terms=True, live_only=True)


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        _drop_fts()
    with op.batch_alter_table("prompt") as batch:
        batch.drop_column("last_used_at")
        batch.drop_column("tags_text")
    if sqlite:
        _create_fts(_OLD_COLS, with_terms=False, live_only=False)
