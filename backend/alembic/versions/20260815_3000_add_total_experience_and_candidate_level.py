"""Add total_experience_months and candidate_level to normalized_resumes.

Revision ID: 20260815_3000
Revises: 20260815_2900
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_3000"
down_revision: str | None = "20260815_2900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("normalized_resumes", sa.Column(
        "total_experience_months", sa.Integer(), nullable=False,
        server_default=sa.text("0"),
    ))
    op.add_column("normalized_resumes", sa.Column(
        "candidate_level", sa.String(32), nullable=False,
        server_default=sa.text("'FRESHER'"),
    ))


def downgrade() -> None:
    op.drop_column("normalized_resumes", "candidate_level")
    op.drop_column("normalized_resumes", "total_experience_months")
