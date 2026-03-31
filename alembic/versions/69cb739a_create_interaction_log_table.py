"""create interaction_log table for taste model signals

Revision ID: 69cb739a
Revises: 69cb7399
Create Date: 2026-03-31 12:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '69cb739a'
down_revision = '69cb7399'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type for signal_type
    signal_type_enum = sa.Enum(
        'save',
        'accepted',
        'rejected',
        'ignored',
        'repeat_visit',
        'search_accepted',
        'onboarding_explicit',
        name='signaltype',
        native_enum=True
    )
    signal_type_enum.create(op.get_bind(), checkfirst=True)

    # Create interaction_log table
    op.create_table(
        'interaction_log',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('signal_type', signal_type_enum, nullable=False),
        sa.Column('place_id', sa.UUID(), nullable=True),
        sa.Column('gain', sa.Float(), nullable=False),
        sa.Column('context', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['place_id'], ['places.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index(op.f('ix_interaction_log_user_id'), 'interaction_log', ['user_id'], unique=False)


def downgrade() -> None:
    # Drop index
    op.drop_index(op.f('ix_interaction_log_user_id'), table_name='interaction_log')

    # Drop table
    op.drop_table('interaction_log')

    # Drop enum type
    signal_type_enum = sa.Enum(name='signaltype', native_enum=True)
    signal_type_enum.drop(op.get_bind(), checkfirst=True)
