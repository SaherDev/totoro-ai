"""chip_confirm interaction type and interaction metadata column (feature 023)

Adds the CHIP_CONFIRM value to the interactiontype enum and a nullable
metadata JSONB column on interactions. Supports the chip_confirm signal
introduced for the onboarding signal tier.

Note on downgrade: PostgreSQL does not support removing a value from an
enum type without recreating the type. Downgrade only drops the metadata
column and leaves the enum value in place — a no-op on rollback that is
functionally harmless (the application stops emitting CHIP_CONFIRM rows).

Revision ID: a7c3d2e9f4b1
Revises: 17f868e70c2c
Create Date: 2026-04-18 18:00:00.000000
"""
from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a7c3d2e9f4b1"
down_revision: Union[str, Sequence[str], None] = "17f868e70c2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add CHIP_CONFIRM to the interactiontype enum (idempotent with IF NOT EXISTS).
    op.execute(
        "ALTER TYPE interactiontype ADD VALUE IF NOT EXISTS 'chip_confirm'"
    )
    # Add nullable JSONB metadata column to interactions.
    op.add_column(
        "interactions",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Drop metadata column only; enum value cannot be safely removed
    # without recreating the type (see module docstring).
    op.drop_column("interactions", "metadata")
