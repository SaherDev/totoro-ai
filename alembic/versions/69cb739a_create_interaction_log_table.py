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
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE signaltype AS ENUM ("
        "'save', 'accepted', 'rejected', 'ignored', "
        "'repeat_visit', 'search_accepted', 'onboarding_explicit'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$"
    )

    op.execute("""
        CREATE TABLE interaction_log (
            id UUID NOT NULL,
            user_id VARCHAR NOT NULL,
            signal_type signaltype NOT NULL,
            place_id VARCHAR,
            gain FLOAT NOT NULL,
            context JSON NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id),
            FOREIGN KEY (place_id) REFERENCES places(id) ON DELETE SET NULL
        )
    """)

    op.create_index(op.f('ix_interaction_log_user_id'), 'interaction_log', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_interaction_log_user_id'), table_name='interaction_log')
    op.drop_table('interaction_log')
    op.execute("DROP TYPE IF EXISTS signaltype")
