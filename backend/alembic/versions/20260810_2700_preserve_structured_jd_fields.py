"""Preserve structured Job Description fields.

Revision ID: 20260810_2700
Revises: 20260810_2600
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260810_2700"
down_revision: str | None = "20260810_2600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_list() -> sa.Column:
    return sa.Column(postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb"))


def upgrade() -> None:
    op.add_column("extracted_job_descriptions", sa.Column("job_title", sa.String(255), nullable=True))
    for name in ("required_skills", "preferred_skills", "education_disciplines"):
        op.add_column("extracted_job_descriptions", sa.Column(name, postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("normalized_job_descriptions", sa.Column("job_title", sa.String(255), nullable=True))
    for name in ("required_skills", "preferred_skills", "education_disciplines", "responsibilities", "certifications"):
        op.add_column("normalized_job_descriptions", sa.Column(name, postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    for name in reversed(("required_skills", "preferred_skills", "education_disciplines", "responsibilities", "certifications")):
        op.drop_column("normalized_job_descriptions", name)
    op.drop_column("normalized_job_descriptions", "job_title")
    for name in reversed(("required_skills", "preferred_skills", "education_disciplines")):
        op.drop_column("extracted_job_descriptions", name)
    op.drop_column("extracted_job_descriptions", "job_title")
