"""PlacesSearchService — DB → stale refresh → cache overlay → external fallback.

Reads only. All writes are delegated to PlaceUpsertService, which owns the
merge policy and event emission. This service touches the cache directly
because cache stores the live half (PlaceObject) which is shaped differently
from the persisted PlaceCore.

Provider-agnostic: collaborates with PlacesClientProtocol; the concrete
implementation (Google, Foursquare, ...) is injected.
"""

from __future__ import annotations

import asyncio
import logging

from ._place_utils import overlay_with_cache
from .models import PlaceCore, PlaceObject, PlaceQuery
from .protocols import (
    PlacesCacheProtocol,
    PlacesClientProtocol,
    PlacesRepoProtocol,
    PlaceUpsertServiceProtocol,
)

logger = logging.getLogger(__name__)

# Cap on parallel external-provider text_search calls during stale refresh.
# Stale rows are rare in steady state (post-30-day-TTL wipe is the main
# source), but a wipe can leave many rows stale at once. Without a cap, a
# single search could fan out into N paid provider calls and trigger 429s.
# Hardcoded for now; lift to config when other places knobs land.
_REFRESH_STALE_CONCURRENCY = 5


class PlacesSearchService:
    def __init__(
        self,
        repo: PlacesRepoProtocol,
        cache: PlacesCacheProtocol,
        client: PlacesClientProtocol,
        upsert_service: PlaceUpsertServiceProtocol,
    ) -> None:
        self._repo = repo
        self._cache = cache
        self._client = client
        self._upsert = upsert_service

    async def find(self, query: PlaceQuery, limit: int = 20) -> list[PlaceObject]:
        """DB → stale refresh → cache overlay → external fallback if empty."""
        db_hits = await self._repo.find(query, limit)
        db_hits = await self._refresh_stale(db_hits)

        if not db_hits:
            return await self._external_fallback(query, limit)

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

    async def _external_fallback(
        self, query: PlaceQuery, limit: int
    ) -> list[PlaceObject]:
        """Cold path: client.search → upsert (via service) → cache → return."""
        results = await self._client.search(query, limit)

        if not results:
            return results

        await self._upsert.upsert_many([_to_core(o) for o in results])
        await self._cache.mset(results)
        return results

    async def _refresh_stale(self, cores: list[PlaceCore]) -> list[PlaceCore]:
        """Refresh stale cores (missing location) from the external provider.

        Concurrency is capped at _REFRESH_STALE_CONCURRENCY to bound provider
        QPS and cost; calls beyond the cap queue rather than firing in
        parallel.
        """
        stale = [c for c in cores if c.location is None or c.location.lat is None]
        if not stale:
            return cores

        no_id = [c for c in stale if not c.id]
        if no_id:
            logger.warning(
                "refresh_stale_cores_missing_id",
                extra={"count": len(no_id), "names": [c.place_name for c in no_id]},
            )

        sem = asyncio.Semaphore(_REFRESH_STALE_CONCURRENCY)

        async def _bounded_text_search(core: PlaceCore) -> list[PlaceObject]:
            async with sem:
                return await self._client.text_search(
                    PlaceQuery(place_name=core.place_name), limit=1
                )

        all_results = await asyncio.gather(
            *[_bounded_text_search(c) for c in stale]
        )

        found: list[PlaceObject] = [r[0] for r in all_results if r]
        if not found:
            return cores

        refreshed = await self._upsert.upsert_many([_to_core(o) for o in found])

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
