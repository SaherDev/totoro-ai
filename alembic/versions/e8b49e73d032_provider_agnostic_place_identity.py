"""provider_agnostic_place_identity

Revision ID: e8b49e73d032
Revises: a1b2c3d4e5f6
Create Date: 2026-03-25 00:55:52.223438

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8b49e73d032'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: split google_place_id into (external_provider, external_id)."""
    # Step 1: Add external_provider column with temporary default
    op.add_column(
        'places',
        sa.Column('external_provider', sa.String(), nullable=False, server_default='google')
    )

    # Step 2: Add external_id column (nullable)
    op.add_column(
        'places',
        sa.Column('external_id', sa.String(), nullable=True)
    )

    # Step 3: Backfill existing data
    op.execute(sa.text("""
        UPDATE places
        SET external_id = google_place_id
        WHERE google_place_id IS NOT NULL
    """))

    # Step 4: Remove default from external_provider
    op.alter_column('places', 'external_provider', server_default=None)

    # Step 5: Create partial unique index
    op.execute(sa.text("""
        CREATE UNIQUE INDEX uq_places_provider_external
        ON places (external_provider, external_id)
        WHERE external_id IS NOT NULL
    """))

    # Step 6: Drop google_place_id column and its index
    op.drop_index('ix_places_google_place_id', table_name='places')
    op.drop_column('places', 'google_place_id')


def downgrade() -> None:
    """Downgrade schema: restore google_place_id column."""
    # Step 1: Add google_place_id back
    op.add_column(
        'places',
        sa.Column('google_place_id', sa.String(), nullable=True)
    )

    # Step 2: Backfill from external_id where provider is 'google'
    op.execute(sa.text("""
        UPDATE places
        SET google_place_id = external_id
        WHERE external_provider = 'google'
    """))

    # Step 3: Create index on google_place_id
    op.create_index('ix_places_google_place_id', 'places', ['google_place_id'])

    # Step 4: Drop unique index
    op.execute(sa.text("DROP INDEX uq_places_provider_external"))

    # Step 5: Drop new columns
    op.drop_column('places', 'external_id')
    op.drop_column('places', 'external_provider')
