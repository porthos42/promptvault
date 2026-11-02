"""import_jobs: background import jobs with progress counters and the drafts payload

prompt.source_url and prompt.license already exist since 0001, so only the table is new.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("importer", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created", sa.Integer, nullable=False, server_default="0"),
        sa.Column("replaced", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("invalid", sa.Integer, nullable=False, server_default="0"),
        sa.Column("refused", sa.Integer, nullable=False, server_default="0"),
        sa.Column("drafts", sa.JSON, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_import_jobs_status", "import_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_import_jobs_status", table_name="import_jobs")
    op.drop_table("import_jobs")
