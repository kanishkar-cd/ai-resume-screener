"""Extend processing_status_enum with IN_PROGRESS and COMPLETED values.

Revision ID: 20260809_2300
Revises: 20260809_2200
Create Date: 2026-08-09 23:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260809_2300"
down_revision: str | None = "20260809_2200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL does not support DROP VALUE, so downgrades leave the values in place.
    # These ALTER TYPE commands are transactional in PostgreSQL 12+.
    op.execute("ALTER TYPE processing_status_enum ADD VALUE IF NOT EXISTS 'IN_PROGRESS'")
    op.execute("ALTER TYPE processing_status_enum ADD VALUE IF NOT EXISTS 'COMPLETED'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed without recreating the type.
    # A no-op downgrade is safe here; the extra values will not be used.
    pass
