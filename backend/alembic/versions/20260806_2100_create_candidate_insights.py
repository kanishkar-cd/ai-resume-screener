"""Create or rename the canonical candidate insights table.

Revision ID: 20260806_2100
Revises: 20260806_2000
Create Date: 2026-08-06 21:00:00
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from app.models.insights import CandidateInsightModel

_INSIGHT_MODEL = CandidateInsightModel
revision: str = "20260806_2100"
down_revision: str | None = "20260806_2000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("candidate_ai_insights") and not inspector.has_table("candidate_insights"):
        op.rename_table("candidate_ai_insights", "candidate_insights")
        for old_name in ("ix_candidate_ai_insights_document_id", "ix_candidate_ai_insights_project_id"):
            op.execute(f'DROP INDEX IF EXISTS "{old_name}"')
        op.create_index("ix_candidate_insights_document_id", "candidate_insights", ["document_id"])
        op.create_index("ix_candidate_insights_project_id", "candidate_insights", ["project_id"])
        return
    if inspector.has_table("candidate_insights"):
        return
    op.create_table(
        "candidate_insights",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        *[sa.Column(name, postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")) for name in ("strengths", "weaknesses", "matched_skills", "missing_skills")],
        sa.Column("score_explanation", sa.Text(), nullable=False),
        sa.Column("recommendation_reason", sa.Text(), nullable=False),
        sa.Column("improvement_suggestions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index("ix_candidate_insights_document_id", "candidate_insights", ["document_id"])
    op.create_index("ix_candidate_insights_project_id", "candidate_insights", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_insights_project_id", table_name="candidate_insights")
    op.drop_index("ix_candidate_insights_document_id", table_name="candidate_insights")
    op.drop_table("candidate_insights")
