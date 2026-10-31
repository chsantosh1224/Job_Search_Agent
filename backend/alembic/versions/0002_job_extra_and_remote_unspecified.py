"""job extra details and remote_unspecified

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE remote_type ADD VALUE IF NOT EXISTS 'remote_unspecified'")
    op.add_column(
        "jobs",
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "extra")
    # Postgres cannot drop a single enum value; rebuild the type without it.
    op.execute("UPDATE jobs SET remote_type = 'unknown' WHERE remote_type = 'remote_unspecified'")
    op.execute("ALTER TYPE remote_type RENAME TO remote_type_old")
    op.execute(
        "CREATE TYPE remote_type AS ENUM ('remote_global', 'remote_india', 'remote_restricted', "
        "'hybrid', 'onsite', 'unknown')"
    )
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN remote_type TYPE remote_type "
        "USING remote_type::text::remote_type"
    )
    op.execute("DROP TYPE remote_type_old")
