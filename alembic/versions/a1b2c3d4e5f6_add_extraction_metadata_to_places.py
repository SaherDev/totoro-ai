"""add_extraction_metadata_to_places

Revision ID: a1b2c3d4e5f6
Revises: f7cf21e03bc7
Create Date: 2026-03-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f7cf21e03bc7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add extraction metadata columns to places table (ADR-017, ADR-018)."""
    op.add_column("places", sa.Column("google_place_id", sa.String(), nullable=True))
    op.add_column("places", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("places", sa.Column("source", sa.String(), nullable=True))
    op.create_index("ix_places_google_place_id", "places", ["google_place_id"])


def downgrade() -> None:
    """Revert extraction metadata columns from places table."""
    op.drop_index("ix_places_google_place_id", "places")
    op.drop_column("places", "source")
    op.drop_column("places", "confidence")
    op.drop_column("places", "google_place_id")
