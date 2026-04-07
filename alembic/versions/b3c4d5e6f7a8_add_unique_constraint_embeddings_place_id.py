"""add unique constraint on embeddings.place_id

Revision ID: b3c4d5e6f7a8
Revises: 94b9f036ae64
Create Date: 2026-04-07 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "94b9f036ae64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the plain index that exists on place_id, then add a unique constraint
    # (which implicitly creates a unique index that satisfies ON CONFLICT).
    op.drop_index("ix_embeddings_place_id", table_name="embeddings", if_exists=True)
    op.create_unique_constraint("uq_embeddings_place_id", "embeddings", ["place_id"])


def downgrade() -> None:
    op.drop_constraint("uq_embeddings_place_id", "embeddings", type_="unique")
    op.create_index("ix_embeddings_place_id", "embeddings", ["place_id"], unique=False)
