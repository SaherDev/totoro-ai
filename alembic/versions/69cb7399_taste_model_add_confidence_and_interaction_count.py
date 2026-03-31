"""taste_model: rename performance_score → eval_score, add confidence and interaction_count

Revision ID: 69cb7399
Revises: f7cf21e03bc7
Create Date: 2026-03-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '69cb7399'
down_revision = 'e8b49e73d032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns before renaming old one
    op.add_column('taste_model', sa.Column('confidence', sa.Float(), nullable=False, server_default='0.0'))
    op.add_column('taste_model', sa.Column('interaction_count', sa.Integer(), nullable=False, server_default='0'))

    # Rename old column
    with op.batch_alter_table('taste_model', schema=None) as batch_op:
        batch_op.alter_column('performance_score', new_column_name='eval_score')


def downgrade() -> None:
    # Reverse: rename eval_score back to performance_score, drop new columns
    with op.batch_alter_table('taste_model', schema=None) as batch_op:
        batch_op.alter_column('eval_score', new_column_name='performance_score')

    op.drop_column('taste_model', 'interaction_count')
    op.drop_column('taste_model', 'confidence')
