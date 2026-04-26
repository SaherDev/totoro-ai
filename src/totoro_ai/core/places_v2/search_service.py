"""PlacesSearchService — DB → stale refresh → cache overlay → Google fallback."""

from __future__ import annotations

import asyncio
import logging

from ._place_utils import overlay_with_cache
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
        """DB → stale refresh → cache overlay → Google fallback if empty."""
        db_hits = await self._repo.find(query, limit)
        db_hits = await self._refresh_stale(db_hits)

        if not db_hits:
            return await self._google_fallback(query, limit)

        results = overlay_with_cache(db_hits, await self._mget_by_cores(db_hits))

        # min_rating: applied post-overlay because rating lives in cache, not DB.
        # Places with no cached rating (None) are kept — we don't know their rating.
        if query.min_rating is not None:
            results = [
                r for r in results
                if r.rating is None or r.rating >= query.min_rating
            ]

        return results

    async def get_by_ids(self, provider_ids: list[str]) -> dict[str, PlaceObject]:
        """Cache mget only — used to enrich a known set of places with live fields."""
        return await self._cache.mget(provider_ids)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _google_fallback(
        self, query: PlaceQuery, limit: int
    ) -> list[PlaceObject]:
        """Cold path: delegate to client.search, save, cache, return."""
        results = await self._client.search(query, limit)

        if not results:
            return results

        saved = await self._repo.save_places([_to_core(o) for o in results])
        await self._cache.mset(results)
        if saved:
            await self._dispatcher.emit_upserted(
                PlaceCoreUpsertedEvent(place_cores=saved)
            )

        return results

    async def _refresh_stale(self, cores: list[PlaceCore]) -> list[PlaceCore]:
        """Refresh stale cores (missing location) from Google in parallel."""
        stale = [c for c in cores if c.location is None or c.location.lat is None]
        if not stale:
            return cores

        no_id = [c for c in stale if not c.id]
        if no_id:
            logger.warning(
                "refresh_stale_cores_missing_id",
                extra={"count": len(no_id), "names": [c.place_name for c in no_id]},
            )

        all_results = await asyncio.gather(*[
            self._client.text_search(PlaceQuery(place_name=c.place_name), limit=1)
            for c in stale
        ])

        found: list[PlaceObject] = [r[0] for r in all_results if r]
        if not found:
            return cores

        pids = [o.provider_id for o in found if o.provider_id]
        existing = await self._repo.get_by_provider_ids(pids)

        to_upsert = [
            (existing.get(o.provider_id or "") or _to_core(o)).model_copy(
                update={"location": o.location}
            )
            for o in found
        ]

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


# ---------------------------------------------------------------------------
# Free functions
# ---------------------------------------------------------------------------

def _to_core(obj: PlaceObject) -> PlaceCore:
    core_fields = PlaceCore.model_fields
    return PlaceCore(**{k: v for k, v in obj.model_dump().items() if k in core_fields})
