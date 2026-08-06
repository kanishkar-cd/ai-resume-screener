"""Create project-owned documents table.

Revision ID: 20260806_1300
Revises: 12c2c7305506
Create Date: 2026-08-06 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.document import DocumentModel

_DOCUMENT_MODEL = DocumentModel

revision: str = "20260806_1300"
down_revision: str | None = "12c2c7305506"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

document_type_enum = postgresql.ENUM(
    "RESUME", "JOB_DESCRIPTION", name="document_type_enum", create_type=False
)
processing_stage_enum = postgresql.ENUM(
    "UPLOAD", name="processing_stage_enum", create_type=False
)
processing_status_enum = postgresql.ENUM(
    "UPLOADED",
    "PARSING_PENDING",
    "PARSED",
    "FAILED",
    name="processing_status_enum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    document_type_enum.create(bind, checkfirst=True)
    processing_stage_enum.create(bind, checkfirst=True)
    processing_status_enum.create(bind, checkfirst=True)
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", document_type_enum, nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "processing_stage",
            processing_stage_enum,
            server_default=sa.text("'UPLOAD'::processing_stage_enum"),
            nullable=False,
        ),
        sa.Column(
            "processing_status",
            processing_status_enum,
            server_default=sa.text("'UPLOADED'::processing_status_enum"),
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
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_documents_project_id_projects", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint("stored_filename", name="uq_documents_stored_filename"),
    )
    op.create_index("ix_documents_project_id", "documents", ["project_id"])
    op.create_index("ix_documents_document_type", "documents", ["document_type"])
    op.create_index(
        "ix_documents_processing_status", "documents", ["processing_status"]
    )
    op.create_index("ix_documents_file_hash", "documents", ["file_hash"])
    op.execute("CREATE INDEX ix_documents_created_at ON documents (created_at DESC)")


def downgrade() -> None:
    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_index("ix_documents_file_hash", table_name="documents")
    op.drop_index("ix_documents_processing_status", table_name="documents")
    op.drop_index("ix_documents_document_type", table_name="documents")
    op.drop_index("ix_documents_project_id", table_name="documents")
    op.drop_table("documents")
    processing_status_enum.drop(op.get_bind(), checkfirst=True)
    processing_stage_enum.drop(op.get_bind(), checkfirst=True)
    document_type_enum.drop(op.get_bind(), checkfirst=True)
