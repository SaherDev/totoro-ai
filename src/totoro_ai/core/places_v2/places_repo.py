"""PlacesRepo — sole writer/reader of the places_v2 DB table."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    MetaData,
    String,
    Table,
    and_,
    case,
    cast,
    distinct,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import LocationContext, PlaceAttributes, PlaceCore, PlaceQuery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table reference — typed columns for native query building
# ---------------------------------------------------------------------------
_metadata = MetaData()
_PlacesV2Table = Table(
    "places_v2",
    _metadata,
    Column("id", String),
    Column("provider_id", String),
    Column("place_name", String),
    Column("category", String),
    Column("tags", ARRAY(String)),
    Column("attributes", JSONB),
    Column("location", JSONB),
    Column("created_at", DateTime(timezone=True)),
    Column("refreshed_at", DateTime(timezone=True)),
)
_t = _PlacesV2Table.c


class PlacesRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_by_ids(self, place_ids: list[str]) -> list[PlaceCore]:
        if not place_ids:
            return []
        stmt = select(_PlacesV2Table).where(_t.id.in_(place_ids))
        result = await self._session.execute(stmt)
        return [_row_to_core(row._mapping) for row in result]

    async def get_by_provider_ids(
        self, provider_ids: list[str]
    ) -> dict[str, PlaceCore]:
        if not provider_ids:
            return {}
        stmt = select(_PlacesV2Table).where(_t.provider_id.in_(provider_ids))
        result = await self._session.execute(stmt)
        return {
            row._mapping["provider_id"]: _row_to_core(row._mapping) for row in result
        }

    async def find(self, query: PlaceQuery, limit: int = 20) -> list[PlaceCore]:
        conditions = []

        if query.place_name:
            conditions.append(_t.place_name.ilike(f"%{query.place_name}%"))

        if query.category:
            conditions.append(_t.category.ilike(f"%{query.category}%"))

        if query.tags:
            conditions.append(_t.tags.contains(query.tags))

        attrs = query.attributes
        if attrs and attrs.cuisine:
            conditions.append(
                _t.attributes["cuisine"].astext.ilike(f"%{attrs.cuisine}%")
            )

        if attrs and attrs.price_hint:
            conditions.append(_t.attributes["price_hint"].astext == attrs.price_hint)

        loc = query.location
        if (
            loc
            and loc.lat is not None
            and loc.lng is not None
            and loc.radius_m is not None
        ):
            geo_lat = cast(_t.location["lat"].astext, Float())
            geo_lng = cast(_t.location["lng"].astext, Float())
            query_box = func.earth_box(
                func.ll_to_earth(loc.lat, loc.lng), float(loc.radius_m)
            )
            conditions.extend(
                [
                    query_box.op("@>")(func.ll_to_earth(geo_lat, geo_lng)),
                    _t.location.isnot(None),
                    _t.location["lat"].astext.isnot(None),
                    _t.location["lng"].astext.isnot(None),
                ]
            )

        stmt = select(_PlacesV2Table)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        result = await self._session.execute(stmt.limit(limit))
        return [_row_to_core(row._mapping) for row in result]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def save_places(self, places: list[PlaceCore]) -> list[PlaceCore]:
        """Bulk INSERT, idempotent on provider_id (no-op on conflict).

        Returns all rows — both newly inserted and those that already existed.
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
                index_where=_t.provider_id.isnot(None),
                set_={"refreshed_at": _t.refreshed_at},
            )
            .returning(*_PlacesV2Table.c)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return [_row_to_core(row._mapping) for row in result]

    async def upsert_places(self, cores: list[PlaceCore]) -> list[PlaceCore]:
        if not cores:
            return []
        results = await asyncio.gather(*[self.upsert_place(c) for c in cores])
        return list(results)

    async def upsert_place(self, core: PlaceCore) -> PlaceCore:
        """Single-row UPSERT with additive merge for curated fields.

        category/tags/attributes merge additively; location takes newest non-NULL.
        """
        now = datetime.now(UTC)
        row = _core_to_dict(core, now)

        insert_stmt = pg_insert(_PlacesV2Table).values([row])
        excl = insert_stmt.excluded
        empty_arr = cast(pg_array([]), ARRAY(String))

        combined_tags = func.coalesce(_t.tags, empty_arr).op("||")(
            func.coalesce(excl.tags, empty_arr)
        )
        x = func.unnest(combined_tags).column_valued("x")
        tags_merge = select(func.array_agg(distinct(x))).scalar_subquery()

        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["provider_id"],
            index_where=_t.provider_id.isnot(None),
            set_={
                "category": func.coalesce(_t.category, excl.category),
                "tags": tags_merge,
                "attributes": _t.attributes.op("||")(excl.attributes),
                "location": func.coalesce(excl.location, _t.location),
                "refreshed_at": case(
                    (excl.location.isnot(None), excl.refreshed_at),
                    else_=_t.refreshed_at,
                ),
            },
        ).returning(*_PlacesV2Table.c)

        result = await self._session.execute(stmt)
        await self._session.commit()
        persisted = result.mappings().one()
        return _row_to_core(persisted)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _core_to_dict(core: PlaceCore, now: datetime) -> dict[str, object]:
    loc = core.location
    return {
        "id": core.id or str(uuid4()),
        "provider_id": core.provider_id,
        "place_name": core.place_name,
        "category": core.category,
        "tags": core.tags or [],
        "attributes": core.attributes.model_dump(exclude_none=True),
        "location": loc.model_dump(exclude_none=True) if loc else None,
        "created_at": core.created_at or now,
        "refreshed_at": core.refreshed_at
        or (now if loc and loc.lat is not None else None),
    }


def _row_to_core(row: object) -> PlaceCore:
    from collections.abc import Mapping

    m = dict(row) if isinstance(row, Mapping) else vars(row)
    attrs_raw = m.get("attributes") or {}
    attributes = (
        PlaceAttributes.model_validate(attrs_raw) if attrs_raw else PlaceAttributes()
    )
    loc_raw = m.get("location")
    location = LocationContext.model_validate(loc_raw) if loc_raw else None
    return PlaceCore(
        id=m.get("id"),
        provider_id=m.get("provider_id"),
        place_name=m["place_name"],
        category=m.get("category"),
        tags=list(m.get("tags") or []),
        attributes=attributes,
        location=location,
        created_at=m.get("created_at"),
        refreshed_at=m.get("refreshed_at"),
    )
