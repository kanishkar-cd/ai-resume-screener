"""Persist hybrid requirement match verdicts.

Revision ID: 20260812_2800
Revises: 20260810_2700
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_2800"
down_revision: str | None = "20260810_2700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("candidate_scores", sa.Column(
        "match_verdicts", postgresql.JSONB(), nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    ))


def downgrade() -> None:
    op.drop_column("candidate_scores", "match_verdicts")
