"""GooglePlacesClient — Places API v1 HTTP adapter."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from ._google_mapper import map_place
from .models import PlaceObject, PlaceQuery
from .tags import AccessibilityTag, SeasonTag, TimeTag

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
    Tag values that don't translate well (time, season, accessibility) are skipped.
    """
    parts: list[str] = []

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


class GooglePlacesClient:
    def __init__(self, api_key: str, http: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._http = http

    async def search(self, query: PlaceQuery, limit: int = 20) -> list[PlaceObject]:
        """Route to text_search or nearby_search based on what the query can express.

        Tags like TimeTag/SeasonTag/AccessibilityTag are skipped in text building,
        so a query with only those tags routes to nearby_search when geo is present.
        """
        loc = query.location
        has_geo = (
            loc is not None
            and loc.lat is not None
            and loc.lng is not None
            and loc.radius_m is not None
        )
        text = _query_to_google_text(query)
        if text:
            return await self.text_search(query, limit)
        if has_geo:
            return await self.nearby_search(query, limit)
        return []

    async def text_search(
        self,
        query: PlaceQuery,
        limit: int = 20,
    ) -> list[PlaceObject]:
        text = _query_to_google_text(query)
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
        if query.open_now is True:
            body["openNow"] = True
        if query.min_rating is not None:
            body["minRating"] = query.min_rating
        return await self._post(":searchText", body, limit)

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
        if query.category:
            body["includedTypes"] = [query.category.value]
        if query.open_now is True:
            body["openNow"] = True
        if query.min_rating is not None:
            body["minRating"] = query.min_rating
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
