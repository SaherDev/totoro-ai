"""Protocol interfaces for the places_v2 library (ADR-038)."""

from __future__ import annotations

from typing import Protocol

from .models import (
    PlaceCore,
    PlaceCoreUpsertedEvent,
    PlaceObject,
    PlaceQuery,
    SavedPlaceView,
    UserPlace,
)


class PlacesRepoProtocol(Protocol):
    async def get_by_ids(self, place_ids: list[str]) -> list[PlaceCore]: ...

    async def get_by_provider_ids(
        self, provider_ids: list[str]
    ) -> dict[str, PlaceCore]: ...

    async def find(
        self, query: PlaceQuery, limit: int = 20
    ) -> list[PlaceCore]: ...

    async def save_places(self, places: list[PlaceCore]) -> list[PlaceCore]: ...

    async def upsert_place(self, core: PlaceCore) -> PlaceCore: ...

    async def upsert_places(self, cores: list[PlaceCore]) -> list[PlaceCore]: ...


class UserPlacesRepoProtocol(Protocol):
    async def get_by_user(self, user_id: str) -> list[UserPlace]: ...

    async def get_by_user_place_id(self, user_place_id: str) -> UserPlace | None: ...

    async def save_user_places(
        self, user_places: list[UserPlace]
    ) -> list[UserPlace]: ...


class PlacesCacheProtocol(Protocol):
    async def mget(
        self, provider_ids: list[str]
    ) -> dict[str, PlaceObject]: ...

    async def mset(
        self, places: list[PlaceObject], ttl_seconds: int = 2_592_000
    ) -> None: ...


class PlacesClientProtocol(Protocol):
    async def search(
        self, query: PlaceQuery, limit: int = 20
    ) -> list[PlaceObject]: ...

    async def text_search(
        self,
        query: PlaceQuery,
        limit: int = 20,
    ) -> list[PlaceObject]: ...

    async def nearby_search(
        self, query: PlaceQuery, limit: int = 20
    ) -> list[PlaceObject]: ...


class PlaceEventDispatcherProtocol(Protocol):
    async def emit_upserted(self, event: PlaceCoreUpsertedEvent) -> None: ...


class PlacesSearchServiceProtocol(Protocol):
    async def find(
        self, query: PlaceQuery, limit: int = 20
    ) -> list[PlaceObject]: ...

    async def get_by_ids(
        self, provider_ids: list[str]
    ) -> dict[str, PlaceObject]: ...


class PlaceUpsertServiceProtocol(Protocol):
    async def upsert(self, candidate: PlaceCore) -> PlaceCore: ...


class UserPlacesServiceProtocol(Protocol):
    async def get_user_places(self, user_id: str) -> list[SavedPlaceView]: ...

    async def update_status(
        self,
        user_place_id: str,
        *,
        visited: bool | None = None,
        liked: bool | None = None,
        needs_approval: bool | None = None,
        note: str | None = None,
    ) -> UserPlace: ...
