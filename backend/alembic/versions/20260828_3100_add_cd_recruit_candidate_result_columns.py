"""Add candidate assessment result columns for CD Recruit.

Revision ID: 20260828_3100
Revises: 20260815_3000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_3100"
down_revision: str | None = "20260815_3000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = [c["name"] for c in inspector.get_columns("candidate_assessments")]

    if "experience_tier" not in existing_cols:
        op.add_column("candidate_assessments", sa.Column("experience_tier", sa.String(length=20), nullable=True))
    if "composite_score" not in existing_cols:
        op.add_column("candidate_assessments", sa.Column("composite_score", sa.Float(), nullable=True))
    if "identity_status" not in existing_cols:
        op.add_column("candidate_assessments", sa.Column("identity_status", sa.String(length=50), nullable=True))
    if "is_identity_verified" not in existing_cols:
        op.add_column("candidate_assessments", sa.Column("is_identity_verified", sa.Boolean(), nullable=True))
    if "started_at" not in existing_cols:
        op.add_column("candidate_assessments", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    if "submitted_at" not in existing_cols:
        op.add_column("candidate_assessments", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("candidate_assessments", "submitted_at")
    op.drop_column("candidate_assessments", "started_at")
    op.drop_column("candidate_assessments", "is_identity_verified")
    op.drop_column("candidate_assessments", "identity_status")
    op.drop_column("candidate_assessments", "composite_score")
