"""add engine_version and score_fingerprint to candidate_scores

Revision ID: 20260816_3100
Revises: 20260815_3000_add_total_experience_and_candidate_level
Create Date: 2026-08-16 21:18:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '20260816_3100'
down_revision = '20260815_3000_add_total_experience_and_candidate_level'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('candidate_scores', sa.Column('engine_version', sa.String(length=50), nullable=True))
    op.add_column('candidate_scores', sa.Column('score_fingerprint', sa.String(length=128), nullable=True))

def downgrade() -> None:
    op.drop_column('candidate_scores', 'score_fingerprint')
    op.drop_column('candidate_scores', 'engine_version')
