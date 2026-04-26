"""GooglePlacesClient — Places API v1 HTTP adapter."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from ._google_mapper import map_place
from ._google_query_builder import build_text_search_params, query_to_google_types
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
    "places.goodForWatchingSports,"
    "places.accessibilityOptions"
)


class GooglePlacesClient:
    def __init__(self, api_key: str, http: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._http = http

    async def search(self, query: PlaceQuery, limit: int = 20) -> list[PlaceObject]:
        """Route to text_search or nearby_search based on what the query can express.

        Tags like TimeTag/SeasonTag/AccessibilityTag produce no text, so a query
        with only those tags falls back to nearby_search when geo is present.
        """
        loc = query.location
        has_geo = (
            loc is not None
            and loc.lat is not None
            and loc.lng is not None
            and loc.radius_m is not None
        )
        if build_text_search_params(query)[0]:
            return await self.text_search(query, limit)
        if has_geo:
            return await self.nearby_search(query, limit)
        return []

    async def text_search(
        self,
        query: PlaceQuery,
        limit: int = 20,
    ) -> list[PlaceObject]:
        text, included_type = build_text_search_params(query)
        if not text:
            return []
        loc = query.location
        body: dict[str, Any] = {
            "textQuery": text,
            "maxResultCount": min(limit, 20),
        }
        if (
            loc
            and loc.lat is not None
            and loc.lng is not None
            and loc.radius_m is not None
        ):
            body["locationRestriction"] = {
                "circle": {
                    "center": {"latitude": loc.lat, "longitude": loc.lng},
                    "radius": float(loc.radius_m),
                }
            }
        if included_type:
            body["includedType"] = included_type
        _apply_common_filters(body, query)
        return await self._post(":searchText", body)

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
        google_types = query_to_google_types(query)
        if google_types:
            body["includedTypes"] = google_types
        _apply_common_filters(body, query)
        return await self._post(":searchNearby", body)

    async def _post(
        self, endpoint: str, body: dict[str, Any]
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
            for raw in (data.get("places") or [])
            if (obj := map_place(raw, now)) is not None
        ]


def _apply_common_filters(body: dict[str, Any], query: PlaceQuery) -> None:
    """Decorate the request body with filters shared by text and nearby search."""
    if query.open_now is True:
        body["openNow"] = True
    if query.min_rating is not None:
        body["minRating"] = query.min_rating
