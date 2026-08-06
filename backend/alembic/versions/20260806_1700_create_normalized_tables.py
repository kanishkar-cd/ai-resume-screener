"""Create Stage 4 normalized information tables.

Revision ID: 20260806_1700
Revises: 20260806_1600
Create Date: 2026-08-06 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.normalized_info import NormalizedJobDescriptionModel, NormalizedResumeModel

_NORMALIZED_MODELS = (NormalizedResumeModel, NormalizedJobDescriptionModel)
revision: str = "20260806_1700"
down_revision: str | None = "20260806_1600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("normalization_metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ruleset_version", sa.String(32), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _list_column(name: str) -> sa.Column:
    return sa.Column(name, postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb"))


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE processing_stage_enum ADD VALUE IF NOT EXISTS 'NORMALIZATION'")
    op.create_table(
        "normalized_resumes",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extracted_resume_id", postgresql.UUID(as_uuid=True), nullable=False),
        *[_list_column(name) for name in ("skills", "education", "companies", "job_titles", "experience")],
        sa.Column("phone", sa.String(32)), sa.Column("email", sa.String(255)),
        *[_list_column(name) for name in ("locations", "languages", "certifications")],
        *_common_columns(),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extracted_resume_id"], ["extracted_resumes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id"), sa.UniqueConstraint("extracted_resume_id"),
    )
    op.create_index("ix_normalized_resumes_document_id", "normalized_resumes", ["document_id"])
    op.create_index("ix_normalized_resumes_extracted_resume_id", "normalized_resumes", ["extracted_resume_id"])
    op.create_index("ix_normalized_resumes_skills_gin", "normalized_resumes", ["skills"], postgresql_using="gin")
    op.create_index("ix_normalized_resumes_job_titles_gin", "normalized_resumes", ["job_titles"], postgresql_using="gin")
    op.create_table(
        "normalized_job_descriptions",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extracted_job_description_id", postgresql.UUID(as_uuid=True), nullable=False),
        *[_list_column(name) for name in ("skills", "degree_requirements", "experience_requirements")],
        sa.Column("domain", sa.String(255)), _list_column("keywords"), *_common_columns(),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extracted_job_description_id"], ["extracted_job_descriptions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id"), sa.UniqueConstraint("extracted_job_description_id"),
    )
    op.create_index("ix_normalized_job_descriptions_document_id", "normalized_job_descriptions", ["document_id"])
    op.create_index("ix_normalized_job_descriptions_extracted_job_description_id", "normalized_job_descriptions", ["extracted_job_description_id"])
    op.create_index("ix_normalized_job_descriptions_skills_gin", "normalized_job_descriptions", ["skills"], postgresql_using="gin")


def downgrade() -> None:
    for name in ("ix_normalized_job_descriptions_skills_gin", "ix_normalized_job_descriptions_extracted_job_description_id", "ix_normalized_job_descriptions_document_id"):
        op.drop_index(name, table_name="normalized_job_descriptions")
    op.drop_table("normalized_job_descriptions")
    for name in ("ix_normalized_resumes_job_titles_gin", "ix_normalized_resumes_skills_gin", "ix_normalized_resumes_extracted_resume_id", "ix_normalized_resumes_document_id"):
        op.drop_index(name, table_name="normalized_resumes")
    op.drop_table("normalized_resumes")
