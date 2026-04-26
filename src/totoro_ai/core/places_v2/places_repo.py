"""PlacesRepo — sole writer/reader of the places_v2 DB table."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PlaceAttributes, PlaceCore, PlaceQuery

logger = logging.getLogger(__name__)


class PlacesRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_by_ids(self, place_ids: list[str]) -> list[PlaceCore]:
        if not place_ids:
            return []
        result = await self._session.execute(
            text("SELECT * FROM places_v2 WHERE id = ANY(:ids)").bindparams(
                ids=place_ids
            )
        )
        return [_row_to_core(row._mapping) for row in result]

    async def get_by_provider_ids(
        self, provider_ids: list[str]
    ) -> dict[str, PlaceCore]:
        if not provider_ids:
            return {}
        result = await self._session.execute(
            text(
                "SELECT * FROM places_v2 WHERE provider_id = ANY(:pids)"
            ).bindparams(pids=provider_ids)
        )
        return {
            row._mapping["provider_id"]: _row_to_core(row._mapping) for row in result
        }

    async def search(self, query: PlaceQuery, limit: int = 20) -> list[PlaceCore]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit}

        if query.text:
            conditions.append(
                """
                to_tsvector('english',
                    coalesce(place_name, '') || ' ' ||
                    coalesce(category, '') || ' ' ||
                    coalesce(array_to_string(tags, ' '), '') || ' ' ||
                    coalesce(attributes->>'cuisine', '')
                ) @@ plainto_tsquery('english', :fts_text)
                """
            )
            params["fts_text"] = query.text

        if query.tags:
            conditions.append("tags @> :tags")
            params["tags"] = query.tags

        if query.cuisine:
            conditions.append("attributes->>'cuisine' ILIKE :cuisine")
            params["cuisine"] = f"%{query.cuisine}%"

        if query.price_hint:
            conditions.append("attributes->>'price_hint' = :price_hint")
            params["price_hint"] = query.price_hint

        loc = query.location
        if (
            loc
            and loc.lat is not None
            and loc.lng is not None
            and loc.radius_m is not None
        ):
            conditions.append(
                "earth_box(ll_to_earth(:geo_lat, :geo_lng), :geo_radius) "
                "@> ll_to_earth(lat, lng)"
            )
            params["geo_lat"] = loc.lat
            params["geo_lng"] = loc.lng
            params["geo_radius"] = float(loc.radius_m)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = text(f"SELECT * FROM places_v2 {where} LIMIT :limit").bindparams(**params)
        result = await self._session.execute(sql)
        return [_row_to_core(row._mapping) for row in result]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def save_places(self, places: list[PlaceCore]) -> list[PlaceCore]:
        """Bulk INSERT, idempotent on provider_id (UPSERT with no-op on conflict).

        Returns all rows — both newly inserted and those that already existed
        (via no-op UPDATE that keeps RETURNING active for conflicting rows).
        """
        if not places:
            return []

        now = datetime.now(UTC)
        rows = [_core_to_dict(p, now) for p in places]

        stmt = (
            pg_insert(_PlacesV2Table)
            .values(rows)
            .on_conflict_do_update(
                index_elements=["provider_id"],
                index_where=text("provider_id IS NOT NULL"),
                set_={"refreshed_at": text("places_v2.refreshed_at")},
            )
            .returning(text("*"))
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return [_row_to_core(row._mapping) for row in result]

    async def upsert_place(self, core: PlaceCore) -> PlaceCore:
        """Single-row UPSERT with additive COALESCE merge for curated fields.

        Curated fields (subcategory, tags, attributes) merge additively.
        Locational fields (lat, lng, address) take new value if provided.
        Identity fields never change.
        """
        now = datetime.now(UTC)
        row = _core_to_dict(core, now)

        stmt = text(
            """
            INSERT INTO places_v2
                (id, provider_id, place_name, category, tags,
                 attributes, lat, lng, address, created_at, refreshed_at)
            VALUES
                (:id, :provider_id, :place_name, :category, :tags,
                 :attributes, :lat, :lng, :address, :created_at, :refreshed_at)
            ON CONFLICT (provider_id) WHERE provider_id IS NOT NULL
            DO UPDATE SET
                category     = COALESCE(places_v2.category, EXCLUDED.category),
                tags         = (
                    SELECT array_agg(DISTINCT x)
                    FROM unnest(
                        COALESCE(places_v2.tags, ARRAY[]::text[]) ||
                        COALESCE(EXCLUDED.tags, ARRAY[]::text[])
                    ) AS x
                ),
                attributes   = places_v2.attributes || EXCLUDED.attributes,
                lat          = COALESCE(EXCLUDED.lat, places_v2.lat),
                lng          = COALESCE(EXCLUDED.lng, places_v2.lng),
                address      = COALESCE(EXCLUDED.address, places_v2.address),
                refreshed_at = CASE
                    WHEN EXCLUDED.lat IS NOT NULL THEN EXCLUDED.refreshed_at
                    ELSE places_v2.refreshed_at
                END
            RETURNING *
            """
        ).bindparams(**row)

        result = await self._session.execute(stmt)
        await self._session.commit()
        persisted = result.mappings().one()
        return _row_to_core(persisted)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Thin table reference for pg_insert (no ORM mapping needed for raw INSERT)
from sqlalchemy import Column, MetaData, Table  # noqa: E402

_metadata = MetaData()
_PlacesV2Table = Table(
    "places_v2",
    _metadata,
    Column("id"),
    Column("provider_id"),
    Column("place_name"),
    Column("category"),
    Column("tags"),
    Column("attributes"),
    Column("lat"),
    Column("lng"),
    Column("address"),
    Column("created_at"),
    Column("refreshed_at"),
)


def _core_to_dict(core: PlaceCore, now: datetime) -> dict[str, object]:
    return {
        "id": core.id or str(uuid4()),
        "provider_id": core.provider_id,
        "place_name": core.place_name,
        "category": core.category,
        "tags": core.tags or [],
        "attributes": core.attributes.model_dump(exclude_none=True),
        "lat": core.lat,
        "lng": core.lng,
        "address": core.address,
        "created_at": core.created_at or now,
        "refreshed_at": core.refreshed_at or (now if core.lat is not None else None),
    }


def _row_to_core(row: object) -> PlaceCore:
    from collections.abc import Mapping

    m = dict(row) if isinstance(row, Mapping) else vars(row)
    attrs_raw = m.get("attributes") or {}
    attributes = (
        PlaceAttributes.model_validate(attrs_raw) if attrs_raw else PlaceAttributes()
    )

    return PlaceCore(
        id=m.get("id"),
        provider_id=m.get("provider_id"),
        place_name=m["place_name"],
        category=m.get("category"),
        tags=list(m.get("tags") or []),
        attributes=attributes,
        lat=m.get("lat"),
        lng=m.get("lng"),
        address=m.get("address"),
        created_at=m.get("created_at"),
        refreshed_at=m.get("refreshed_at"),
    )
