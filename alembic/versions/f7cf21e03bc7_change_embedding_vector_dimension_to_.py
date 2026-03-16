"""change_embedding_vector_dimension_to_1024

Revision ID: f7cf21e03bc7
Revises: cf635906e8ad
Create Date: 2026-03-16 14:55:10.165184

"""
from typing import Sequence, Union

from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = 'f7cf21e03bc7'
down_revision: Union[str, Sequence[str], None] = 'cf635906e8ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change embeddings.vector from 1536 to 1024 dimensions (ADR-040: Voyage 3.5-lite)."""
    op.alter_column(
        'embeddings',
        'vector',
        existing_type=Vector(1536),
        type_=Vector(1024),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Revert embeddings.vector from 1024 back to 1536 dimensions."""
    op.alter_column(
        'embeddings',
        'vector',
        existing_type=Vector(1024),
        type_=Vector(1536),
        existing_nullable=False,
    )
