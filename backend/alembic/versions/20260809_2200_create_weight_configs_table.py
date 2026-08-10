"""Create weight_configs table.

Revision ID: 20260809_2200
Revises: 20260808_2100
Create Date: 2026-08-09 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260809_2200"
down_revision: str | None = "20260808_2100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("weight_configs"):
        op.create_table(
            "weight_configs",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "weights",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "passing_score",
                sa.Float(),
                server_default=sa.text("60.0"),
                nullable=False,
            ),
            sa.Column(
                "min_experience_years",
                sa.Float(),
                server_default=sa.text("0.0"),
                nullable=False,
            ),
            sa.Column("required_degree", sa.String(length=255), nullable=True),
            sa.Column(
                "required_certifications",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "mandatory_skills",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "preferred_skills",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "knockout_rules",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "custom_keywords",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "version",
                sa.Integer(),
                server_default=sa.text("1"),
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
                ["project_id"],
                ["projects.id"],
                name="fk_weight_configs_project_id_projects",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_weight_configs"),
            sa.UniqueConstraint("project_id", name="uq_weight_configs_project_id"),
        )
        op.create_index(
            "ix_weight_configs_project_id", "weight_configs", ["project_id"]
        )
        op.execute("CREATE INDEX ix_weight_configs_created_at ON weight_configs (created_at DESC)")

    if inspector.has_table("project_weight_configs"):
        op.execute("""
            INSERT INTO weight_configs (
                id, project_id, weights, passing_score, min_experience_years,
                required_degree, required_certifications, mandatory_skills,
                preferred_skills, knockout_rules, custom_keywords, version,
                created_at, updated_at
            )
            SELECT
                id, project_id,
                jsonb_build_object(
                    'skills', skills_weight,
                    'experience', experience_weight,
                    'projects', projects_weight,
                    'education', education_weight,
                    'certifications', certifications_weight,
                    'languages', languages_weight
                ) AS weights,
                passing_score, min_experience_years,
                required_degree, required_certifications, mandatory_skills,
                preferred_skills, knockout_rules, custom_keywords, version,
                created_at, updated_at
            FROM project_weight_configs
            ON CONFLICT (project_id) DO NOTHING;
        """)


def downgrade() -> None:
    op.drop_index("ix_weight_configs_created_at", table_name="weight_configs")
    op.drop_index("ix_weight_configs_project_id", table_name="weight_configs")
    op.drop_table("weight_configs")
