"""drop_consult_logs_feedback_columns

Feature 021: Drop intent, accepted, selected_place_id from consult_logs.
Feedback signals are now tracked via the interactions table (ADR-058).

Revision ID: a2b3c4d5e6f7
Revises: f4d8e1a23c56
Create Date: 2026-04-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f4d8e1a23c56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("consult_logs", "intent")
    op.drop_column("consult_logs", "accepted")
    op.drop_column("consult_logs", "selected_place_id")


def downgrade() -> None:
    op.add_column(
        "consult_logs",
        sa.Column(
            "intent",
            sa.String(),
            nullable=False,
            server_default=sa.text("'consult'"),
        ),
    )
    op.add_column(
        "consult_logs",
        sa.Column("accepted", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "consult_logs",
        sa.Column("selected_place_id", sa.String(), nullable=True),
    )
