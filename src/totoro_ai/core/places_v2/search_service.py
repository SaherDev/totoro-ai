"""PlacesSearchService — orchestrates DB → cache → Google discovery flow."""

from __future__ import annotations

import asyncio
import logging

from .models import PlaceCore, PlaceCoreUpsertedEvent, PlaceObject, PlaceQuery
from .protocols import (
    PlaceEventDispatcherProtocol,
    PlacesCacheProtocol,
    PlacesClientProtocol,
    PlacesRepoProtocol,
)

logger = logging.getLogger(__name__)


class PlacesSearchService:
    def __init__(
        self,
        repo: PlacesRepoProtocol,
        cache: PlacesCacheProtocol,
        client: PlacesClientProtocol,
        event_dispatcher: PlaceEventDispatcherProtocol,
        db_min_hits: int = 3,
    ) -> None:
        self._repo = repo
        self._cache = cache
        self._client = client
        self._dispatcher = event_dispatcher
        self._db_min_hits = db_min_hits

    async def search(self, query: PlaceQuery, limit: int = 20) -> list[PlaceObject]:
        """Warm path: DB → cache overlay → return if ≥ db_min_hits.
        Cold path: Google → dual-write cache + DB → emit events → return merged.
        """
        db_hits = await self._repo.search(query, limit)

        # Inline stale refresh for rows with missing location data
        db_hits = await self._refresh_stale(db_hits)

        if len(db_hits) >= self._db_min_hits:
            return self._overlay(db_hits, await self._mget_by_cores(db_hits))

        # Cold path
        new_objects = await self._client.text_search(query, limit)
        if not new_objects:
            # Return what we have even below threshold
            return self._overlay(db_hits, await self._mget_by_cores(db_hits))

        await self._cache.mset(new_objects)

        new_cores_input = [_to_core(obj) for obj in new_objects]
        persisted = await self._repo.save_places(new_cores_input)

        if persisted:
            await self._dispatcher.emit_upserted(
                PlaceCoreUpsertedEvent(place_cores=persisted)
            )

        # Merge DB hits + new results, dedup by provider_id, cap at limit
        merged = _merge(db_hits, new_objects, persisted, limit)
        return merged

    async def get_by_ids(self, provider_ids: list[str]) -> dict[str, PlaceObject]:
        """Cache mget only — used to enrich a known set of places with live fields."""
        return await self._cache.mget(provider_ids)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _refresh_stale(self, cores: list[PlaceCore]) -> list[PlaceCore]:
        """Refresh stale cores (missing location) from Google in parallel."""
        stale = [c for c in cores if c.location is None or c.location.lat is None]
        if not stale:
            return cores

        # Parallel Google lookups
        all_results = await asyncio.gather(*[
            self._client.text_search(PlaceQuery(text=c.place_name), limit=1)
            for c in stale
        ])

        found: list[PlaceObject] = [r[0] for r in all_results if r]
        if not found:
            return cores

        # Pull existing DB records by provider_id in one batch
        pids = [o.provider_id for o in found if o.provider_id]
        existing = await self._repo.get_by_provider_ids(pids)

        # Merge: apply fresh location onto existing curated core
        to_upsert = [
            (existing.get(o.provider_id or "") or _to_core(o)).model_copy(
                update={"location": o.location}
            )
            for o in found
        ]

        # Batch upsert + single event
        refreshed = await self._repo.upsert_places(to_upsert)
        if refreshed:
            await self._dispatcher.emit_upserted(
                PlaceCoreUpsertedEvent(place_cores=refreshed)
            )

        fresh_map = {c.id: c for c in refreshed if c.id}
        return [fresh_map.get(c.id or "", c) for c in cores]

    async def _mget_by_cores(
        self, cores: list[PlaceCore]
    ) -> dict[str, PlaceObject]:
        provider_ids = [c.provider_id for c in cores if c.provider_id]
        if not provider_ids:
            return {}
        return await self._cache.mget(provider_ids)

    @staticmethod
    def _overlay(
        cores: list[PlaceCore],
        cached: dict[str, PlaceObject],
    ) -> list[PlaceObject]:
        result = []
        for core in cores:
            if core.provider_id and core.provider_id in cached:
                cached_obj = cached[core.provider_id]
                # Build PlaceObject from core fields + cached live fields
                obj = PlaceObject(
                    **core.model_dump(),
                    rating=cached_obj.rating,
                    hours=cached_obj.hours,
                    phone=cached_obj.phone,
                    website=cached_obj.website,
                    popularity=cached_obj.popularity,
                    cached_at=cached_obj.cached_at,
                )
            else:
                obj = PlaceObject(**core.model_dump())
            result.append(obj)
        return result


# ---------------------------------------------------------------------------
# Free functions
# ---------------------------------------------------------------------------

def _to_core(obj: PlaceObject) -> PlaceCore:
    core_fields = PlaceCore.model_fields
    return PlaceCore(**{k: v for k, v in obj.model_dump().items() if k in core_fields})


def _merge(
    db_hits: list[PlaceCore],
    new_objects: list[PlaceObject],
    persisted: list[PlaceCore],
    limit: int,
) -> list[PlaceObject]:
    """Merge DB overlay results with newly fetched objects, dedup by provider_id."""
    seen: set[str] = set()
    result: list[PlaceObject] = []

    # Build a map of persisted cores by provider_id for ID enrichment
    persisted_by_pid = {c.provider_id: c for c in persisted if c.provider_id}

    for core in db_hits:
        pid = core.provider_id or ""
        if pid and pid in seen:
            continue
        seen.add(pid)
        result.append(PlaceObject(**core.model_dump()))

    for obj in new_objects:
        pid = obj.provider_id or ""
        if pid and pid in seen:
            continue
        seen.add(pid)
        # Enrich with DB-assigned id if available
        if pid and pid in persisted_by_pid:
            obj = PlaceObject(**{**obj.model_dump(), "id": persisted_by_pid[pid].id})
        result.append(obj)

    return result[:limit]
