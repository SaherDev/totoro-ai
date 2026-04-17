"""make_interactions_place_id_nullable_drop_fk

Drop FK constraint on interactions.place_id and make the column nullable.
Discovered places from consult aren't persisted yet, so the FK blocks
recommendation signals for those places.

Revision ID: 17f868e70c2c
Revises: 5d579fed8509
Create Date: 2026-04-18 00:32:06.392658

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '17f868e70c2c'
down_revision: Union[str, Sequence[str], None] = '5d579fed8509'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "interaction_log_place_id_fkey", "interactions", type_="foreignkey"
    )
    op.alter_column("interactions", "place_id", nullable=True)


def downgrade() -> None:
    op.alter_column("interactions", "place_id", nullable=False)
    op.create_foreign_key(
        "interaction_log_place_id_fkey",
        "interactions",
        "places",
        ["place_id"],
        ["id"],
    )
