"""Create Stage 6 candidate scores.

Revision ID: 20260806_1900
Revises: 20260806_1800
Create Date: 2026-08-06 19:00:00
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from app.models.scoring import CandidateScoreModel

_SCORE_MODEL = CandidateScoreModel
revision: str = "20260806_1900"
down_revision: str | None = "20260806_1800"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    recommendation = postgresql.ENUM("STRONG_MATCH", "RECOMMENDED", "NEEDS_REVIEW", "NOT_RECOMMENDED", name="recommendation_level_enum", create_type=False)
    recommendation.create(op.get_bind(), checkfirst=True)
    score = lambda name: sa.Column(name, sa.Numeric(5, 2), nullable=False)
    op.create_table(
        "candidate_scores",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        *[score(f"{name}_score") for name in ("skills", "experience", "projects", "education", "certifications", "languages")],
        sa.Column("component_scores", postgresql.JSONB(), nullable=False),
        sa.Column("weighted_scores", postgresql.JSONB(), nullable=False),
        score("raw_total_score"), score("weighted_total_score"),
        sa.Column("penalty_total", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("bonus_total", sa.Numeric(5, 2), nullable=False, server_default="0"),
        score("final_score"), score("confidence"),
        sa.Column("recommendation", recommendation, nullable=False),
        sa.Column("is_knocked_out", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("knockout_reason", sa.Text()),
        sa.Column("penalty_summary", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("bonus_summary", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("weight_config_version", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id"),
    )
    for name in ("document_id", "project_id", "recommendation"):
        op.create_index(f"ix_candidate_scores_{name}", "candidate_scores", [name])


def downgrade() -> None:
    for name in ("recommendation", "project_id", "document_id"):
        op.drop_index(f"ix_candidate_scores_{name}", table_name="candidate_scores")
    op.drop_table("candidate_scores")
    postgresql.ENUM(name="recommendation_level_enum").drop(op.get_bind(), checkfirst=True)
