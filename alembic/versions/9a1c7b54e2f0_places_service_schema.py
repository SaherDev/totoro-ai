"""places_service_schema

Feature 019: reshape the `places` table for PlacesService (ADR-054).

=============================================================================
⚠️  OPERATOR: RUN `python scripts/seed_migration.py` BEFORE `alembic upgrade head`.

The seed script relocates legacy data (cuisine, price_range, ambiance →
attributes JSONB; lat/lng/address for rows with a provider_id → Redis Tier 2
cache; place_type backfill via a heuristic ladder). If the script finds any
row it cannot confidently classify, it defaults that row's place_type to
'services' and exits code 2 to force your review. Investigate the
`place_type_defaulted` lines in scripts/seed_migration.log, fix or accept
the defaults (re-run with `--accept-defaults`), and only then run this
migration. This migration drops the legacy columns — their data is lost
if you skip the seed step.
=============================================================================

Revision ID: 9a1c7b54e2f0
Revises: 2d4472dd48a1
Create Date: 2026-04-14 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9a1c7b54e2f0"
down_revision: str | None = "2d4472dd48a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reshape `places` table for PlacesService (feature 019, ADR-054).

    Order of operations:
      1. Add new columns (all nullable at first so existing rows are valid).
      2. Backfill `provider_id` from the legacy `(external_provider, external_id)`
         composite — build namespaced `"{provider}:{id}"` strings.
      3. Backfill `attributes` JSONB from legacy `cuisine`, `price_range`, `ambiance`
         (idempotent with the seed script: the script already did this for every
         row that had data; this UPDATE is a safety net for anything the script
         missed).
      4. Create the partial unique index on `provider_id`.
      5. Create the `(user_id, place_type)` composite index.
      6. Create the FTS GIN index on `place_name + subcategory`.
      7. Backfill `place_type` for any row that still has NULL (seed script should
         have handled this; we default to 'services' here as a last resort so the
         NOT NULL constraint can be applied).
      8. Tighten `place_type` to NOT NULL.
      9. Drop the legacy composite unique constraint.
      10. Drop the legacy columns.
      11. Drop the legacy `address` NOT NULL constraint (column is being dropped).

    Rollback (downgrade) restores the legacy columns as nullable but does NOT
    reverse the JSONB relocation — data in `attributes` stays put. This
    asymmetry is documented.
    """
    # ------------------------------------------------------------------
    # 1. Add new columns (nullable at first)
    # ------------------------------------------------------------------
    op.add_column("places", sa.Column("place_type", sa.String(), nullable=True))
    op.add_column("places", sa.Column("subcategory", sa.String(), nullable=True))
    op.add_column("places", sa.Column("tags", postgresql.JSONB(), nullable=True))
    op.add_column(
        "places", sa.Column("attributes", postgresql.JSONB(), nullable=True)
    )
    op.add_column("places", sa.Column("provider_id", sa.String(), nullable=True))

    # ------------------------------------------------------------------
    # 2. Backfill provider_id from legacy composite pair
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE places
        SET provider_id = external_provider || ':' || external_id
        WHERE external_provider IS NOT NULL
          AND external_id        IS NOT NULL
          AND provider_id        IS NULL
        """
    )

    # ------------------------------------------------------------------
    # 3. Backfill attributes JSONB from legacy scalar columns (safety net).
    #    The seed script should have handled this; this UPDATE catches rows
    #    the script missed (e.g. rows added between the script run and the
    #    alembic upgrade).
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE places
        SET attributes = jsonb_strip_nulls(jsonb_build_object(
            'cuisine',    cuisine,
            'price_hint', CASE price_range
                            WHEN 'low'  THEN 'cheap'
                            WHEN 'mid'  THEN 'moderate'
                            WHEN 'high' THEN 'expensive'
                            ELSE NULL
                          END,
            'ambiance',   ambiance
        ))
        WHERE attributes IS NULL
          AND (cuisine IS NOT NULL OR price_range IS NOT NULL OR ambiance IS NOT NULL)
        """
    )

    # ------------------------------------------------------------------
    # 4. Partial unique index on provider_id
    # ------------------------------------------------------------------
    op.create_index(
        "uq_places_provider_id",
        "places",
        ["provider_id"],
        unique=True,
        postgresql_where=sa.text("provider_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 5. (user_id, place_type) composite index
    # ------------------------------------------------------------------
    op.create_index(
        "ix_places_user_type",
        "places",
        ["user_id", "place_type"],
    )

    # ------------------------------------------------------------------
    # 6. FTS GIN index
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE INDEX places_fts_idx
          ON places
          USING gin(
            to_tsvector('english',
              coalesce(place_name, '') || ' ' || coalesce(subcategory, ''))
          )
        """
    )

    # ------------------------------------------------------------------
    # 7. Last-resort place_type backfill (should be empty after seed script)
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE places
        SET place_type = 'services'
        WHERE place_type IS NULL
        """
    )

    # ------------------------------------------------------------------
    # 8. Tighten place_type to NOT NULL
    # ------------------------------------------------------------------
    op.alter_column("places", "place_type", nullable=False)

    # ------------------------------------------------------------------
    # 9. Drop the legacy composite unique constraint
    # ------------------------------------------------------------------
    op.drop_constraint("uq_places_provider_external", "places", type_="unique")

    # ------------------------------------------------------------------
    # 10 + 11. Drop the legacy columns
    # ------------------------------------------------------------------
    op.drop_column("places", "ambiance")
    op.drop_column("places", "confidence")
    op.drop_column("places", "external_id")
    op.drop_column("places", "external_provider")
    op.drop_column("places", "validated_at")
    op.drop_column("places", "lng")
    op.drop_column("places", "lat")
    op.drop_column("places", "price_range")
    op.drop_column("places", "cuisine")
    op.drop_column("places", "address")


def downgrade() -> None:
    """Restore legacy columns as nullable.

    Asymmetry: JSONB relocation is NOT reversed. Data that the seed script
    moved into `attributes.cuisine`, `attributes.price_hint`,
    `attributes.ambiance` stays in `attributes`. The legacy `cuisine`,
    `price_range`, `ambiance` columns come back empty. Similarly, `lat`,
    `lng`, `address` come back empty — the Tier 2 Redis cache is not
    copied back into PostgreSQL.
    """
    # Restore legacy columns (all nullable on downgrade to avoid crashing
    # on existing rows).
    op.add_column("places", sa.Column("address", sa.String(), nullable=True))
    op.add_column("places", sa.Column("cuisine", sa.String(), nullable=True))
    op.add_column("places", sa.Column("price_range", sa.String(), nullable=True))
    op.add_column("places", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("places", sa.Column("lng", sa.Float(), nullable=True))
    op.add_column(
        "places",
        sa.Column(
            "validated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "places", sa.Column("external_provider", sa.String(), nullable=True)
    )
    op.add_column("places", sa.Column("external_id", sa.String(), nullable=True))
    op.add_column("places", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("places", sa.Column("ambiance", sa.String(), nullable=True))

    # Backfill external_provider + external_id from provider_id where possible.
    op.execute(
        """
        UPDATE places
        SET external_provider = split_part(provider_id, ':', 1),
            external_id       = split_part(provider_id, ':', 2)
        WHERE provider_id IS NOT NULL
        """
    )

    # Recreate the composite unique constraint.
    op.create_unique_constraint(
        "uq_places_provider_external",
        "places",
        ["external_provider", "external_id"],
    )

    # Drop the new indexes.
    op.execute("DROP INDEX IF EXISTS places_fts_idx")
    op.drop_index("ix_places_user_type", table_name="places")
    op.drop_index("uq_places_provider_id", table_name="places")

    # Drop the new columns.
    op.drop_column("places", "provider_id")
    op.drop_column("places", "attributes")
    op.drop_column("places", "tags")
    op.drop_column("places", "subcategory")
    op.drop_column("places", "place_type")
