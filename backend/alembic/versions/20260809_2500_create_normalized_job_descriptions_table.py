"""Create normalized_job_descriptions table.

Revision ID: 20260809_2500
Revises: 20260809_2400
Create Date: 2026-08-09 23:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260809_2500"
down_revision: str | None = "20260809_2400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "normalized_job_descriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "extracted_job_description_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "skills",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "degree_requirements",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "experience_requirements",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column(
            "keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "normalization_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "ruleset_version",
            sa.String(length=32),
            server_default=sa.text("'1.0'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_normalized_jds_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extracted_job_description_id"],
            ["extracted_job_descriptions.id"],
            name="fk_normalized_jds_extracted_jd_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_normalized_job_descriptions"),
        sa.UniqueConstraint("document_id", name="uq_normalized_jds_document_id"),
    )
    op.create_index(
        "ix_normalized_jds_document_id", "normalized_job_descriptions", ["document_id"]
    )
    op.execute(
        "CREATE INDEX ix_normalized_jds_created_at ON normalized_job_descriptions (created_at DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_normalized_jds_created_at", table_name="normalized_job_descriptions")
    op.drop_index("ix_normalized_jds_document_id", table_name="normalized_job_descriptions")
    op.drop_table("normalized_job_descriptions")
