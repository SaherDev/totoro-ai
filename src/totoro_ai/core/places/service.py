"""PlacesService — the public data-layer entry point for every caller.

Phase 3 ships create/create_batch/get/get_batch/get_by_external_id. The
`enrich_batch` method is a stub that raises `NotImplementedError` until
Phase 4 (US2 recall) and Phase 5 (US3 consult) fill in the cache/fetch paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from totoro_ai.core.places.models import (
    PlaceCreate,
    PlaceObject,
    PlaceProvider,
)
from totoro_ai.core.places.repository import PlacesRepository

if TYPE_CHECKING:
    # Forward reference — PlacesCache lands in Phase 4 (T038).
    from totoro_ai.core.places.cache import PlacesCache  # pragma: no cover
    from totoro_ai.core.places.places_client import PlacesClient


class PlacesService:
    """Facade over PlacesRepository + PlacesCache + PlacesClient.

    Callers receive a fully-wired instance via `Depends(get_places_service)`.
    During Phase 3, `cache` and `client` are optional (the create/get paths
    don't need them); Phase 4/5 make them required for `enrich_batch`.
    """

    def __init__(
        self,
        repo: PlacesRepository,
        cache: PlacesCache | None = None,
        client: PlacesClient | None = None,
    ) -> None:
        self._repo = repo
        self._cache = cache
        self._client = client

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    async def create(self, data: PlaceCreate) -> PlaceObject:
        return await self._repo.create(data)

    async def create_batch(self, items: list[PlaceCreate]) -> list[PlaceObject]:
        return await self._repo.create_batch(items)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, place_id: str) -> PlaceObject | None:
        return await self._repo.get(place_id)

    async def get_batch(self, place_ids: list[str]) -> list[PlaceObject]:
        return await self._repo.get_batch(place_ids)

    async def get_by_external_id(
        self, provider: PlaceProvider, external_id: str
    ) -> PlaceObject | None:
        return await self._repo.get_by_external_id(provider, external_id)

    # ------------------------------------------------------------------
    # Enrichment — stub until Phase 4/5.
    # ------------------------------------------------------------------
    async def enrich_batch(
        self,
        places: list[PlaceObject],
        geo_only: bool = False,
    ) -> list[PlaceObject]:
        raise NotImplementedError("enrich_batch lands in US2 (Phase 4) / US3 (Phase 5)")
