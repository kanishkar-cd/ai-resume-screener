"""Create Stage 5 project weight configurations.

Revision ID: 20260806_1800
Revises: 20260806_1700
Create Date: 2026-08-06 18:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.weight_config import WeightConfigModel

_WEIGHT_CONFIG_MODEL = WeightConfigModel
revision: str = "20260806_1800"
down_revision: str | None = "20260806_1700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_weight_configs",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        *[sa.Column(name, sa.Numeric(5, 2), nullable=False, server_default=default) for name, default in (("skills_weight", "40.00"), ("experience_weight", "25.00"), ("projects_weight", "15.00"), ("education_weight", "10.00"), ("certifications_weight", "5.00"), ("languages_weight", "5.00"), ("passing_score", "70.00"))],
        sa.Column("min_experience_years", sa.Numeric(4, 1), nullable=False, server_default="0.0"),
        sa.Column("required_degree", sa.String(255)),
        *[sa.Column(name, postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")) for name in ("required_certifications", "mandatory_skills", "preferred_skills", "knockout_rules", "custom_keywords")],
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("skills_weight + experience_weight + projects_weight + education_weight + certifications_weight + languages_weight = 100.00", name="ck_total_weights"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index("ix_project_weight_configs_project_id", "project_weight_configs", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_weight_configs_project_id", table_name="project_weight_configs")
    op.drop_table("project_weight_configs")
