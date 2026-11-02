"""seed_hash: fingerprint of the seed content last applied to a seeded prompt

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prompt", sa.Column("seed_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    # Plain DROP COLUMN (SQLite >= 3.35): a batch table rebuild would drop the FTS triggers.
    op.execute("ALTER TABLE prompt DROP COLUMN seed_hash")
