"""rename_consult_logs_to_recommendations

Rename consult_logs table to recommendations (ADR-060, supersedes ADR-053).
Metadata-only operation — no table rewrite, instant.

Revision ID: 5d579fed8509
Revises: a2b3c4d5e6f7
Create Date: 2026-04-17 23:24:06.788403

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5d579fed8509'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("consult_logs", "recommendations")
    op.execute(
        "ALTER INDEX ix_consult_logs_user_id RENAME TO ix_recommendations_user_id"
    )


def downgrade() -> None:
    op.rename_table("recommendations", "consult_logs")
    op.execute(
        "ALTER INDEX ix_recommendations_user_id RENAME TO ix_consult_logs_user_id"
    )
