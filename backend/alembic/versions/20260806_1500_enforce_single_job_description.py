"""Enforce one active Job Description per project.

Revision ID: 20260806_1500
Revises: 20260806_1400
Create Date: 2026-08-06 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_1500"
down_revision: str | None = "20260806_1400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY project_id ORDER BY created_at DESC, id DESC
                   ) AS position
            FROM documents
            WHERE document_type = 'JOB_DESCRIPTION'
              AND deleted_at IS NULL
        )
        UPDATE documents
        SET deleted_at = NOW()
        FROM ranked
        WHERE documents.id = ranked.id AND ranked.position > 1
        """
    )
    op.create_index(
        "uq_project_active_job_description",
        "documents",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text(
            "document_type = 'JOB_DESCRIPTION' AND deleted_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_project_active_job_description", table_name="documents"
    )
