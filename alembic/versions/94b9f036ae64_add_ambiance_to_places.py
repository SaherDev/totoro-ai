"""add ambiance to places

Revision ID: 94b9f036ae64
Revises: 69cb739a
Create Date: 2026-03-31 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "94b9f036ae64"
down_revision: str | None = "69cb739a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("places", sa.Column("ambiance", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("places", "ambiance")
