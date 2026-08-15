"""Add projects column to normalized_resumes.

Revision ID: 20260815_2900
Revises: 20260812_2800
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260815_2900"
down_revision: str | None = "20260812_2800"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("normalized_resumes", sa.Column(
        "projects", postgresql.JSONB(), nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    ))


def downgrade() -> None:
    op.drop_column("normalized_resumes", "projects")
