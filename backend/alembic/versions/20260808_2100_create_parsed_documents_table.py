"""Create parsed_documents table for Stage 2 parsing.

Revision ID: 20260808_2100
Revises: e5a985802002
Create Date: 2026-08-08 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260808_2100"
down_revision: str | None = "20260806_2100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("parsed_documents"):
        return
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
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("parser_engine", sa.String(length=32), nullable=False),
        sa.Column("parsing_duration_ms", sa.Float(), nullable=False),
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
        sa.UniqueConstraint("document_id", name="uq_parsed_documents_document_id"),
    )
    op.create_index(
        "ix_parsed_documents_document_id", "parsed_documents", ["document_id"]
    )
    op.create_index(
        "ix_parsed_documents_created_at", "parsed_documents", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_parsed_documents_created_at", table_name="parsed_documents")
    op.drop_index("ix_parsed_documents_document_id", table_name="parsed_documents")
    op.drop_table("parsed_documents")
