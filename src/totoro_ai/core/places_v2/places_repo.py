"""PlacesRepo — sole writer/reader of the places_v2 DB table."""

from __future__ import annotations

import asyncio
import json
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
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    LocationContext,
    PlaceCategory,
    PlaceCore,
    PlaceQuery,
    PlaceTag,
)

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
    Column("tags", JSONB),
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
            conditions.append(_t.category == query.category.value)

        if query.tags:
            # AND semantics: every requested tag value must be present
            for tag_val in query.tags:
                conditions.append(
                    _t.tags.op("@>")(
                        cast(json.dumps([{"value": tag_val}]), JSONB)
                    )
                )

        loc = query.location
        if loc and loc.city:
            conditions.append(_t.location["city"].astext.ilike(f"%{loc.city}%"))
        if loc and loc.country:
            conditions.append(_t.location["country"].astext == loc.country)
        if loc and loc.neighborhood:
            conditions.append(
                _t.location["neighborhood"].astext.ilike(f"%{loc.neighborhood}%")
            )

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

        if query.created_after:
            conditions.append(_t.created_at >= query.created_after)
        if query.created_before:
            conditions.append(_t.created_at <= query.created_before)

        stmt = select(_PlacesV2Table)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        sort_col = getattr(_t, query.sort_by) if query.sort_by else _t.created_at
        stmt = stmt.order_by(sort_col.desc() if query.sort_desc else sort_col.asc())

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

        category coalesces (keep existing); tags and location take newest non-NULL.
        Requires provider_id — without it the conflict target won't fire and
        concurrent calls can create duplicate rows.
        """
        if core.provider_id is None:
            logger.warning(
                "upsert_place_no_provider_id",
                extra={"place_name": core.place_name},
            )
        now = datetime.now(UTC)
        row = _core_to_dict(core, now)

        insert_stmt = pg_insert(_PlacesV2Table).values([row])
        excl = insert_stmt.excluded

        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["provider_id"],
            index_where=_t.provider_id.isnot(None),
            set_={
                "category": func.coalesce(_t.category, excl.category),
                "tags": func.coalesce(excl.tags, _t.tags),
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
        "category": core.category.value if core.category else None,
        "tags": [t.model_dump() for t in core.tags] or None,
        "location": loc.model_dump(exclude_none=True) if loc else None,
        "created_at": core.created_at or now,
        "refreshed_at": core.refreshed_at
        or (now if loc and loc.lat is not None else None),
    }


def _row_to_core(row: object) -> PlaceCore:
    from collections.abc import Mapping

    m = dict(row) if isinstance(row, Mapping) else vars(row)
    tags = [PlaceTag.model_validate(t) for t in (m.get("tags") or [])]
    loc_raw = m.get("location")
    location = LocationContext.model_validate(loc_raw) if loc_raw else None
    return PlaceCore(
        id=m.get("id"),
        provider_id=m.get("provider_id"),
        place_name=m["place_name"],
        category=PlaceCategory(m["category"]) if m.get("category") else None,
        tags=tags,
        location=location,
        created_at=m.get("created_at"),
        refreshed_at=m.get("refreshed_at"),
    )
