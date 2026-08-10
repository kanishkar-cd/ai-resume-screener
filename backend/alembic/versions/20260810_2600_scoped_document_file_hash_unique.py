"""Scope document file_hash uniqueness to project and document_type.

Revision ID: 20260810_2600
Revises: 20260809_2500
Create Date: 2026-08-10 16:50:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_2600"
down_revision: str | None = "20260809_2500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_project_document_file_hash",
        "documents",
        ["project_id", "file_hash", "document_type"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_project_document_file_hash", table_name="documents")
