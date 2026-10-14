"""Scope Zoho attachment uniqueness per Job Opening.

Revision ID: 20261014_3300
Revises: 20261013_3200
Create Date: 2026-10-14 12:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_3300"
down_revision: str | None = "20261013_3200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_project_zoho_attachment_id", table_name="documents")
    op.create_index(
        "uq_project_zoho_opening_attachment",
        "documents",
        [
            "project_id",
            sa.text("(metadata_json->>'zoho_job_opening_id')"),
            sa.text("(metadata_json->>'zoho_attachment_id')"),
        ],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND (metadata_json->>'zoho_attachment_id') IS NOT NULL AND (metadata_json->>'zoho_job_opening_id') IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_project_zoho_opening_attachment", table_name="documents")
    op.create_index(
        "uq_project_zoho_attachment_id",
        "documents",
        ["project_id", sa.text("(metadata_json->>'zoho_attachment_id')")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND (metadata_json->>'zoho_attachment_id') IS NOT NULL"),
    )
