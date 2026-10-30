"""baseline schema + FTS5 search index

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "category",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("category.id", ondelete="SET NULL")),
        sa.Column("icon", sa.String(50)),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_category_slug", "category", ["slug"], unique=True)

    op.create_table(
        "tag",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_tag_name", "tag", ["name"])

    op.create_table(
        "prompt",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("seed_id", sa.String(200), unique=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("category.id", ondelete="SET NULL")),
        sa.Column("variables", sa.JSON, nullable=False),
        sa.Column("model_hints", sa.Text),
        sa.Column("output_format", sa.String(200)),
        sa.Column("difficulty", sa.String(20), nullable=False, server_default="beginner"),
        sa.Column("prompt_type", sa.String(20), nullable=False, server_default="template"),
        sa.Column("disclaimer", sa.Text),
        sa.Column("source", sa.String(200), nullable=False, server_default="user"),
        sa.Column("source_url", sa.String(1000)),
        sa.Column("license", sa.String(100)),
        sa.Column("is_favorite", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("rating", sa.Integer),
        sa.Column("use_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("body_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_prompt_category_id", "prompt", ["category_id"])
    op.create_index("ix_prompt_body_hash", "prompt", ["body_hash"])

    op.create_table(
        "prompt_tag",
        sa.Column(
            "prompt_id",
            sa.String(36),
            sa.ForeignKey("prompt.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id", sa.Integer, sa.ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
        ),
    )

    op.create_table(
        "prompt_revision",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "prompt_id",
            sa.String(36),
            sa.ForeignKey("prompt.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("prompt_id", "version"),
    )
    op.create_index("ix_prompt_revision_prompt_id", "prompt_revision", ["prompt_id"])

    if op.get_bind().dialect.name == "sqlite":
        # External-content FTS5 index kept in sync by triggers. Tags are indexed in M1.
        op.execute(
            "CREATE VIRTUAL TABLE prompt_fts USING fts5("
            "title, description, body, content='prompt', content_rowid='rowid', "
            "tokenize='porter unicode61')"
        )
        op.execute(
            "CREATE TRIGGER prompt_fts_ai AFTER INSERT ON prompt BEGIN "
            "INSERT INTO prompt_fts(rowid, title, description, body) "
            "VALUES (new.rowid, new.title, new.description, new.body); END"
        )
        op.execute(
            "CREATE TRIGGER prompt_fts_ad AFTER DELETE ON prompt BEGIN "
            "INSERT INTO prompt_fts(prompt_fts, rowid, title, description, body) "
            "VALUES ('delete', old.rowid, old.title, old.description, old.body); END"
        )
        op.execute(
            "CREATE TRIGGER prompt_fts_au AFTER UPDATE ON prompt BEGIN "
            "INSERT INTO prompt_fts(prompt_fts, rowid, title, description, body) "
            "VALUES ('delete', old.rowid, old.title, old.description, old.body); "
            "INSERT INTO prompt_fts(rowid, title, description, body) "
            "VALUES (new.rowid, new.title, new.description, new.body); END"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for trg in ("prompt_fts_ai", "prompt_fts_ad", "prompt_fts_au"):
            op.execute(f"DROP TRIGGER IF EXISTS {trg}")
        op.execute("DROP TABLE IF EXISTS prompt_fts")
    op.drop_table("prompt_revision")
    op.drop_table("prompt_tag")
    op.drop_table("prompt")
    op.drop_table("tag")
    op.drop_table("category")
