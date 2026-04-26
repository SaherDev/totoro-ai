"""UserPlacesService — combines user_places + places repos and live-field enrichment."""

from __future__ import annotations

from .models import PlaceObject, SavedPlaceView, UserPlace
from .protocols import (
    PlacesRepoProtocol,
    PlacesSearchServiceProtocol,
    UserPlacesRepoProtocol,
)


class UserPlacesService:
    def __init__(
        self,
        places_repo: PlacesRepoProtocol,
        user_places_repo: UserPlacesRepoProtocol,
        search: PlacesSearchServiceProtocol,
    ) -> None:
        self._places_repo = places_repo
        self._user_places_repo = user_places_repo
        self._search = search

    async def get_user_places(self, user_id: str) -> list[SavedPlaceView]:
        """Three reads: user_places → places → cache overlay. Zero writes."""
        user_places = await self._user_places_repo.get_by_user(user_id)
        if not user_places:
            return []

        place_ids = [up.place_id for up in user_places]
        cores = await self._places_repo.get_by_ids(place_ids)
        cores_by_id = {c.id: c for c in cores if c.id}

        provider_ids = [c.provider_id for c in cores if c.provider_id]
        cached = await self._search.get_by_ids(provider_ids) if provider_ids else {}

        result: list[SavedPlaceView] = []
        for up in user_places:
            core = cores_by_id.get(up.place_id)
            if core is None:
                continue

            if core.provider_id and core.provider_id in cached:
                cached_obj = cached[core.provider_id]
                place = PlaceObject(
                    **core.model_dump(),
                    rating=cached_obj.rating,
                    hours=cached_obj.hours,
                    phone=cached_obj.phone,
                    website=cached_obj.website,
                    popularity=cached_obj.popularity,
                    cached_at=cached_obj.cached_at,
                )
            else:
                place = PlaceObject(**core.model_dump())

            result.append(SavedPlaceView(place=place, user_data=up))

        return result

    async def update_status(
        self,
        user_place_id: str,
        *,
        visited: bool | None = None,
        liked: bool | None = None,
        needs_approval: bool | None = None,
        note: str | None = None,
    ) -> UserPlace:
        """Mutate status flags and note. Returns updated UserPlace."""
        existing = await self._user_places_repo.get_by_user_place_id(user_place_id)
        if existing is None:
            raise ValueError(f"user_place_id not found: {user_place_id}")

        updates = {
            k: v
            for k, v in {
                "visited": visited,
                "liked": liked,
                "needs_approval": needs_approval,
                "note": note,
            }.items()
            if v is not None
        }
        updated = existing.model_copy(update=updates)
        saved = await self._user_places_repo.save_user_places([updated])
        return saved[0]
