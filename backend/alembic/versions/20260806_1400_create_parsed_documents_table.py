"""Create parsed documents and extend document processing state.

Revision ID: 20260806_1400
Revises: e5a985802002
Create Date: 2026-08-06 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.parsed_document import ParsedDocumentModel

_PARSED_DOCUMENT_MODEL = ParsedDocumentModel

revision: str = "20260806_1400"
down_revision: str | None = "e5a985802002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE processing_stage_enum ADD VALUE IF NOT EXISTS 'INGESTION'")
        op.execute("ALTER TYPE processing_stage_enum ADD VALUE IF NOT EXISTS 'PARSING'")
        op.execute("ALTER TYPE processing_stage_enum ADD VALUE IF NOT EXISTS 'COMPLETED'")
        op.execute("ALTER TYPE processing_stage_enum ADD VALUE IF NOT EXISTS 'FAILED'")
        op.execute("ALTER TYPE processing_status_enum ADD VALUE IF NOT EXISTS 'IN_PROGRESS'")
        op.execute("ALTER TYPE processing_status_enum ADD VALUE IF NOT EXISTS 'COMPLETED'")

    op.execute("ALTER TABLE documents ALTER COLUMN processing_stage DROP DEFAULT")
    op.execute(
        "UPDATE documents SET processing_stage = 'INGESTION'::processing_stage_enum "
        "WHERE processing_stage = 'UPLOAD'::processing_stage_enum"
    )
    op.execute(
        "ALTER TABLE documents ALTER COLUMN processing_stage "
        "SET DEFAULT 'INGESTION'::processing_stage_enum"
    )
    op.add_column("documents", sa.Column("error_message", sa.Text(), nullable=True))

    op.create_table(
        "parsed_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("parser_engine", sa.String(length=64), nullable=False),
        sa.Column("parsing_duration_ms", sa.Float(), nullable=False),
        sa.Column(
            "parsing_metadata",
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
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_parsed_documents_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_parsed_documents"),
        sa.UniqueConstraint(
            "document_id", name="uq_parsed_documents_document_id"
        ),
    )
    op.create_index(
        "ix_parsed_documents_document_id",
        "parsed_documents",
        ["document_id"],
    )
    op.create_index(
        "ix_parsed_documents_language", "parsed_documents", ["language"]
    )
    op.create_index(
        "ix_parsed_documents_parser_engine",
        "parsed_documents",
        ["parser_engine"],
    )


def downgrade() -> None:
    op.drop_index("ix_parsed_documents_parser_engine", table_name="parsed_documents")
    op.drop_index("ix_parsed_documents_language", table_name="parsed_documents")
    op.drop_index("ix_parsed_documents_document_id", table_name="parsed_documents")
    op.drop_table("parsed_documents")
    op.drop_column("documents", "error_message")
    op.execute("ALTER TABLE documents ALTER COLUMN processing_stage DROP DEFAULT")
    op.execute(
        "UPDATE documents SET processing_stage = 'UPLOAD'::processing_stage_enum "
        "WHERE processing_stage <> 'UPLOAD'::processing_stage_enum"
    )
    op.execute(
        "ALTER TABLE documents ALTER COLUMN processing_stage "
        "SET DEFAULT 'UPLOAD'::processing_stage_enum"
    )
