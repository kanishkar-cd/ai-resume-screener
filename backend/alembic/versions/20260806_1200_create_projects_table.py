"""Create projects table.

Revision ID: 20260806_1200
Revises:
Create Date: 2026-08-06 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.project import ProjectModel

_PROJECT_MODEL = ProjectModel

revision: str = "20260806_1200"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

project_status_enum = postgresql.ENUM(
    "DRAFT",
    "ACTIVE",
    "COMPLETED",
    "ARCHIVED",
    name="project_status_enum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    project_status_enum.create(bind, checkfirst=True)
    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_role", sa.String(length=255), nullable=False),
        sa.Column("department", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            project_status_enum,
            server_default=sa.text("'DRAFT'::project_status_enum"),
            nullable=False,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )
    op.create_index("ix_projects_status", "projects", ["status"], unique=False)
    op.create_index(
        "ix_projects_target_role", "projects", ["target_role"], unique=False
    )
    op.execute("CREATE INDEX ix_projects_created_at ON projects (created_at DESC)")


def downgrade() -> None:
    op.drop_index("ix_projects_created_at", table_name="projects")
    op.drop_index("ix_projects_target_role", table_name="projects")
    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_table("projects")
    project_status_enum.drop(op.get_bind(), checkfirst=True)
