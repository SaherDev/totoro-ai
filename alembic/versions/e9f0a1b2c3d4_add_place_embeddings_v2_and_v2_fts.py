"""add_place_embeddings_v2_and_v2_fts

Creates the `place_embeddings_v2` table (one vector per place_id) and
the `places_v2.search_vector` generated tsvector column, plus the
indexes needed for hybrid search:

  * HNSW index on `place_embeddings_v2.vector` (cosine ops) — kNN side
  * GIN index on `places_v2.search_vector` — full-text side

The generated tsvector pulls scalar fields directly and JSONB array
values via `jsonb_path_query_array($[*].value)`. Listing those JSONB
columns explicitly here keeps the generated expression IMMUTABLE
(required for STORED columns) and avoids tokenizing JSON keys.

Revision ID: e9f0a1b2c3d4
Revises: d1e2f3a4b5c6
Create Date: 2026-04-27 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | tuple[str, ...] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Keep in sync with EMBEDDING_DIMENSIONS in
# src/totoro_ai/core/places_v2/embeddings_repo.py.
EMBEDDING_DIMENSIONS = 1024


def upgrade() -> None:
    # ------------------------------------------------------------------
    # place_embeddings_v2 — one row per place_id, FK → places_v2 with
    # ON DELETE CASCADE so a wiped place takes its vector with it.
    # ------------------------------------------------------------------
    op.create_table(
        "place_embeddings_v2",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column(
            "place_id",
            sa.String,
            sa.ForeignKey("places_v2.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("vector", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("model_name", sa.String, nullable=False),
        sa.Column("text_hash", sa.String, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # HNSW index on the vector column (cosine distance). Approximate kNN
    # but ~100x faster than a seq scan past ~100k rows. Built lazily —
    # writes don't block.
    op.execute(
        "CREATE INDEX place_embeddings_v2_vector_hnsw_idx "
        "ON place_embeddings_v2 USING hnsw (vector vector_cosine_ops)"
    )

    # ------------------------------------------------------------------
    # places_v2.search_vector — generated tsvector over the lexical
    # fields the recall path actually queries. 'simple' config (no
    # stemming) keeps non-English place names intact.
    #
    # JSONB arrays are flattened with jsonb_path_query_array($[*].value)
    # so only the value strings land in the tsvector — JSON keys like
    # "type" / "source" / "value" stay out of the index.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE places_v2 ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('simple',
                coalesce(place_name, '') || ' ' ||
                coalesce(category, '') || ' ' ||
                coalesce(
                    jsonb_path_query_array(place_name_aliases, '$[*].value')::text,
                    ''
                ) || ' ' ||
                coalesce(
                    jsonb_path_query_array(tags, '$[*].value')::text,
                    ''
                ) || ' ' ||
                coalesce(location->>'neighborhood', '') || ' ' ||
                coalesce(location->>'city', '') || ' ' ||
                coalesce(location->>'country', '')
            )
        ) STORED
        """
    )

    op.execute(
        "CREATE INDEX places_v2_fts_idx "
        "ON places_v2 USING gin(search_vector)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS places_v2_fts_idx")
    op.execute("ALTER TABLE places_v2 DROP COLUMN IF EXISTS search_vector")

    op.execute("DROP INDEX IF EXISTS place_embeddings_v2_vector_hnsw_idx")
    op.drop_table("place_embeddings_v2")
