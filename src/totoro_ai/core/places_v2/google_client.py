"""GooglePlacesClient — Places API v1 HTTP adapter."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from ._google_mapper import map_place
from .models import PlaceObject, PlaceQuery

logger = logging.getLogger(__name__)

_PLACES_API_BASE = "https://places.googleapis.com/v1/places"
_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.addressComponents,"
    "places.location,"
    "places.rating,"
    "places.regularOpeningHours,"
    "places.nationalPhoneNumber,"
    "places.websiteUri,"
    "places.types,"
    "places.userRatingCount,"
    "places.timeZone,"
    "places.priceLevel,"
    "places.dineIn,"
    "places.takeout,"
    "places.delivery,"
    "places.reservable,"
    "places.servesBreakfast,"
    "places.servesBrunch,"
    "places.servesLunch,"
    "places.servesDinner,"
    "places.servesBeer,"
    "places.servesWine,"
    "places.servesCocktails,"
    "places.servesVegetarianFood,"
    "places.outdoorSeating,"
    "places.liveMusic,"
    "places.menuForChildren,"
    "places.allowsDogs,"
    "places.goodForChildren,"
    "places.goodForGroups,"
    "places.goodForWatchingSports"
)


class GooglePlacesClient:
    def __init__(self, api_key: str, http: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._http = http

    async def text_search(self, text: str, limit: int = 20) -> list[PlaceObject]:
        if not text:
            return []
        return await self._post(
            ":searchText", {"textQuery": text, "maxResultCount": min(limit, 20)}, limit
        )

    async def nearby_search(
        self, query: PlaceQuery, limit: int = 20
    ) -> list[PlaceObject]:
        loc = query.location
        if not loc or loc.lat is None or loc.lng is None or loc.radius_m is None:
            logger.warning("nearby_search_requires_full_location")
            return []
        body: dict[str, Any] = {
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": loc.lat, "longitude": loc.lng},
                    "radius": float(loc.radius_m),
                }
            },
            "maxResultCount": min(limit, 20),
        }
        return await self._post(":searchNearby", body, limit)

    async def _post(
        self, endpoint: str, body: dict[str, Any], limit: int
    ) -> list[PlaceObject]:
        try:
            response = await self._http.post(
                f"{_PLACES_API_BASE}{endpoint}",
                json=body,
                headers={
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": _FIELD_MASK,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.exception(
                "google_places_request_error", extra={"endpoint": endpoint}
            )
            return []

        now = datetime.now(UTC)
        return [
            obj
            for raw in (data.get("places") or [])[:limit]
            if (obj := map_place(raw, now)) is not None
        ]
