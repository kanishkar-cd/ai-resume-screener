"""Create Stage 3 extracted information tables.

Revision ID: 20260806_1600
Revises: 20260806_1500
Create Date: 2026-08-06 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.extracted_info import ExtractedJobDescriptionModel, ExtractedResumeModel

_EXTRACTED_MODELS = (ExtractedResumeModel, ExtractedJobDescriptionModel)

revision: str = "20260806_1600"
down_revision: str | None = "20260806_1500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE processing_stage_enum ADD VALUE IF NOT EXISTS 'EXTRACTION'")

    json_list = sa.text("'[]'::jsonb")
    json_dict = sa.text("'{}'::jsonb")
    op.create_table(
        "extracted_resumes",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_name", sa.String(255)), sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(64)), sa.Column("designation", sa.String(255)),
        sa.Column("location", sa.String(255)),
        *[sa.Column(name, postgresql.JSONB(), nullable=False, server_default=json_list) for name in ("skills", "education", "experience", "projects", "certifications", "companies", "languages")],
        sa.Column("raw_metadata", postgresql.JSONB(), nullable=False, server_default=json_dict),
        sa.Column("confidence_scores", postgresql.JSONB(), nullable=False, server_default=json_dict),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index("ix_extracted_resumes_document_id", "extracted_resumes", ["document_id"])
    op.create_index("ix_extracted_resumes_email", "extracted_resumes", ["email"])
    op.create_table(
        "extracted_job_descriptions",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(255)),
        *[sa.Column(name, postgresql.JSONB(), nullable=False, server_default=json_list) for name in ("skills", "responsibilities", "education", "experience", "certifications", "keywords")],
        sa.Column("raw_metadata", postgresql.JSONB(), nullable=False, server_default=json_dict),
        sa.Column("confidence_scores", postgresql.JSONB(), nullable=False, server_default=json_dict),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index("ix_extracted_job_descriptions_document_id", "extracted_job_descriptions", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_extracted_job_descriptions_document_id", table_name="extracted_job_descriptions")
    op.drop_table("extracted_job_descriptions")
    op.drop_index("ix_extracted_resumes_email", table_name="extracted_resumes")
    op.drop_index("ix_extracted_resumes_document_id", table_name="extracted_resumes")
    op.drop_table("extracted_resumes")
