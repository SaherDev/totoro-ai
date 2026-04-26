"""PlaceUpsertService — additive merge + event emission for save flows."""

from __future__ import annotations

from .models import PlaceCore, PlaceCoreUpsertedEvent
from .protocols import PlaceEventDispatcherProtocol, PlacesRepoProtocol


class PlaceUpsertService:
    def __init__(
        self,
        repo: PlacesRepoProtocol,
        event_dispatcher: PlaceEventDispatcherProtocol,
    ) -> None:
        self._repo = repo
        self._dispatcher = event_dispatcher

    async def upsert(self, candidate: PlaceCore) -> PlaceCore:
        """Run additive COALESCE merge, emit event, return persisted."""
        persisted = await self._repo.upsert_place(candidate)
        await self._dispatcher.emit_upserted(
            PlaceCoreUpsertedEvent(place_cores=[persisted])
        )
        return persisted
