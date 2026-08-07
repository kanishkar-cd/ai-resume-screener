"""Create Stage 7 candidate rankings.

Revision ID: 20260806_2000
Revises: 20260806_1900
Create Date: 2026-08-06 20:00:00
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from app.models.ranking import CandidateRankingModel

_RANKING_MODEL = CandidateRankingModel
revision: str = "20260806_2000"
down_revision: str | None = "20260806_1900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    recommendation = postgresql.ENUM(name="recommendation_level_enum", create_type=False)
    op.create_table(
        "candidate_rankings",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_score_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank_position", sa.Integer(), nullable=False),
        sa.Column("percentile", sa.Numeric(5, 2), nullable=False),
        sa.Column("final_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("recommendation", recommendation, nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column("previous_rank", sa.Integer()),
        sa.Column("rank_change", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_score_id"], ["candidate_scores.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id"), sa.UniqueConstraint("candidate_score_id"),
        sa.UniqueConstraint("project_id", "rank_position", name="uq_project_rank_position"),
    )
    op.create_index("ix_candidate_rankings_project_rank", "candidate_rankings", ["project_id", "rank_position"])
    op.create_index("ix_candidate_rankings_document_id", "candidate_rankings", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_rankings_document_id", table_name="candidate_rankings")
    op.drop_index("ix_candidate_rankings_project_rank", table_name="candidate_rankings")
    op.drop_table("candidate_rankings")
