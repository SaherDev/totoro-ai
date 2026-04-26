"""PlacesSearchService — DB → stale refresh → cache overlay → Google fallback."""

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
from .tags import AccessibilityTag, SeasonTag, TimeTag

logger = logging.getLogger(__name__)

# Tag values that add noise to a Google text query — Google doesn't interpret
# time-of-day, seasons, or accessibility codes as place descriptors.
_GOOGLE_SKIP_VALUES: frozenset[str] = frozenset(
    {t.value for t in TimeTag}
    | {t.value for t in SeasonTag}
    | {t.value for t in AccessibilityTag}
)


def _query_to_google_text(query: PlaceQuery) -> str:
    """Convert a PlaceQuery into a natural-language Google textQuery string.

    Uses query.text if provided; otherwise builds from category + tags.
    Tag values that don't translate to text search (time, season, accessibility)
    are skipped automatically.
    """
    parts: list[str] = []

    if query.text:
        parts.append(query.text)
    else:
        if query.place_name:
            parts.append(query.place_name)
        if query.category:
            parts.append(query.category.value.replace("_", " "))

    if query.tags:
        for tag_val in query.tags:
            if tag_val not in _GOOGLE_SKIP_VALUES:
                parts.append(str(tag_val).replace("_", " "))

    # dict.fromkeys preserves insertion order and deduplicates
    return " ".join(dict.fromkeys(parts))


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

        return self._overlay(db_hits, await self._mget_by_cores(db_hits))

    async def get_by_ids(self, provider_ids: list[str]) -> dict[str, PlaceObject]:
        """Cache mget only — used to enrich a known set of places with live fields."""
        return await self._cache.mget(provider_ids)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _google_fallback(
        self, query: PlaceQuery, limit: int
    ) -> list[PlaceObject]:
        """Cold path: translate PlaceQuery → Google search, save, cache, return."""
        loc = query.location
        has_geo = (
            loc is not None
            and loc.lat is not None
            and loc.lng is not None
            and loc.radius_m is not None
        )

        text = _query_to_google_text(query)

        if text:
            # text_search handles both plain and geo-restricted queries
            results = await self._client.text_search(
                text,
                limit,
                location=loc if has_geo else None,
                open_now=query.open_now,
                min_rating=query.min_rating,
            )
        elif has_geo:
            # geo-only (no text, no tags) — nearby search
            results = await self._client.nearby_search(query, limit)
        else:
            return []

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

        all_results = await asyncio.gather(*[
            self._client.text_search(c.place_name, limit=1)
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

    @staticmethod
    def _overlay(
        cores: list[PlaceCore],
        cached: dict[str, PlaceObject],
    ) -> list[PlaceObject]:
        result = []
        for core in cores:
            if core.provider_id and core.provider_id in cached:
                cached_obj = cached[core.provider_id]
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
