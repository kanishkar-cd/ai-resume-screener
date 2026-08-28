"""Create candidate_assessments table.

Revision ID: 20260815_3000
Revises: 20260812_2800
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260815_3000"
down_revision: str | None = "20260812_2800"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    tables = inspector.get_table_names()

    if "candidate_assessments" not in tables:
        op.create_table(
            "candidate_assessments",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("requisition_ref", sa.String(100), nullable=False),
            sa.Column("drive_id", sa.String(100), nullable=True),
            sa.Column("external_candidate_ref", sa.String(255), nullable=False),
            sa.Column("idempotency_key", sa.String(64), nullable=True),
            sa.Column("experience_tier", sa.String(20), nullable=True),
            sa.Column("assessment_link", sa.String(1024), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("session_status", sa.String(50), nullable=False, server_default="not_started"),
            sa.Column("score_status", sa.String(50), nullable=False, server_default="not_graded"),
            sa.Column("composite_score_band", sa.String(50), nullable=True),
            sa.Column("decision", sa.String(50), nullable=True),
            sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_candidate_assessments_project_id", "candidate_assessments", ["project_id"])
        op.create_index("ix_candidate_assessments_document_id", "candidate_assessments", ["document_id"])
        op.create_index("ix_candidate_assessments_requisition_ref", "candidate_assessments", ["requisition_ref"])
        op.create_index("ix_candidate_assessments_ext_candidate_ref", "candidate_assessments", ["external_candidate_ref"])
        op.create_index("ix_candidate_assessments_idempotency_key", "candidate_assessments", ["idempotency_key"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    tables = inspector.get_table_names()

    if "candidate_assessments" in tables:
        op.drop_index("ix_candidate_assessments_idempotency_key", table_name="candidate_assessments")
        op.drop_index("ix_candidate_assessments_ext_candidate_ref", table_name="candidate_assessments")
        op.drop_index("ix_candidate_assessments_requisition_ref", table_name="candidate_assessments")
        op.drop_index("ix_candidate_assessments_document_id", table_name="candidate_assessments")
        op.drop_index("ix_candidate_assessments_project_id", table_name="candidate_assessments")
        op.drop_table("candidate_assessments")
