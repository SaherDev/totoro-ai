"""PlacesSearchService — DB → stale refresh → cache overlay."""

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
    ) -> None:
        self._repo = repo
        self._cache = cache
        self._client = client
        self._dispatcher = event_dispatcher

    async def find(self, query: PlaceQuery, limit: int = 20) -> list[PlaceObject]:
        """DB → stale refresh → cache overlay → return."""
        db_hits = await self._repo.find(query, limit)
        db_hits = await self._refresh_stale(db_hits)
        return self._overlay(db_hits, await self._mget_by_cores(db_hits))

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
            self._client.text_search(c.place_name, limit=1)
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


