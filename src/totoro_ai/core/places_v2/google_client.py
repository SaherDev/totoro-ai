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

# ---------------------------------------------------------------------------
# Outbound mapping: our tag/category values → Google place type strings
# ---------------------------------------------------------------------------

# Cuisine and dietary tag values → Google place type ID
_TAG_TO_GOOGLE_TYPE: dict[str, str] = {
    # cuisine
    "Thai": "thai_restaurant",
    "Japanese": "japanese_restaurant",
    "Korean": "korean_restaurant",
    "Chinese": "chinese_restaurant",
    "Italian": "italian_restaurant",
    "French": "french_restaurant",
    "Mexican": "mexican_restaurant",
    "Indian": "indian_restaurant",
    "Vietnamese": "vietnamese_restaurant",
    "Mediterranean": "mediterranean_restaurant",
    "American": "american_restaurant",
    "Greek": "greek_restaurant",
    "Spanish": "spanish_restaurant",
    "Turkish": "turkish_restaurant",
    "Indonesian": "indonesian_restaurant",
    "Middle Eastern": "middle_eastern_restaurant",
    "Brazilian": "brazilian_restaurant",
    "Seafood": "seafood_restaurant",
    "Steakhouse": "steak_house",
    # dietary
    "vegan": "vegan_restaurant",
    "vegetarian": "vegetarian_restaurant",
    "halal": "halal_restaurant",
}

# Our PlaceCategory values → Google place type ID
_CATEGORY_TO_GOOGLE_TYPE: dict[str, str] = {
    "restaurant": "restaurant",
    "cafe": "cafe",
    "bar": "bar",
    "pub": "pub",
    "bakery": "bakery",
    "dessert_shop": "dessert_shop",
    "ice_cream_shop": "ice_cream_shop",
    "street_food": "street_food",
    "food_court": "food_court",
    "food_market": "food_market",
    "juice_bar": "juice_bar",
    "tea_house": "tea_house",
    "brewery": "brewery",
    "winery": "winery",
    "distillery": "distillery",
    "grocery_store": "grocery_store",
    "supermarket": "supermarket",
    "convenience_store": "convenience_store",
    "shopping_mall": "shopping_mall",
    "bookstore": "book_store",
    "pharmacy": "pharmacy",
    "electronics_store": "electronics_store",
    "night_market": "night_market",
    "farmers_market": "farmers_market",
    "flea_market": "flea_market",
    "museum": "museum",
    "art_gallery": "art_gallery",
    "historical_site": "historical_landmark",
    "monument": "monument",
    "shrine": "shrine",
    "temple": "hindu_temple",
    "mosque": "mosque",
    "church": "church",
    "viewpoint": "observation_deck",
    "landmark": "tourist_attraction",
    "theme_park": "theme_park",
    "amusement_park": "amusement_park",
    "zoo": "zoo",
    "aquarium": "aquarium",
    "botanical_garden": "botanical_garden",
    "cinema": "movie_theater",
    "theater": "performing_arts_theater",
    "concert_hall": "concert_hall",
    "live_music_venue": "live_music_venue",
    "nightclub": "night_club",
    "comedy_club": "comedy_club",
    "karaoke": "karaoke",
    "arcade": "arcade",
    "bowling_alley": "bowling_alley",
    "park": "park",
    "beach": "beach",
    "garden": "garden",
    "lake": "lake",
    "hiking_trail": "hiking_area",
    "campground": "campground",
    "gym": "fitness_center",
    "yoga_studio": "yoga_studio",
    "pilates_studio": "pilates_studio",
    "spa": "spa",
    "massage": "massage",
    "hot_spring": "hot_spring",
    "salon": "beauty_salon",
    "barber": "barber_shop",
    "climbing_gym": "climbing_gym",
    "skate_park": "skate_park",
    "golf_course": "golf_course",
    "swimming_pool": "swimming_pool",
    "sports_club": "sports_club",
    "stadium": "stadium",
    "arena": "arena",
    "atm": "atm",
    "bank": "bank",
    "post_office": "post_office",
    "gas_station": "gas_station",
    "parking": "parking",
    "laundry": "laundromat",
    "hotel": "hotel",
    "hostel": "hostel",
    "guesthouse": "guest_house",
    "bed_and_breakfast": "bed_and_breakfast",
    "resort": "resort_hotel",
    "vacation_rental": "vacation_rental",
    "airport": "airport",
    "train_station": "train_station",
    "metro_station": "subway_station",
    "bus_terminal": "bus_station",
    "ferry_terminal": "ferry_terminal",
    "coworking_space": "coworking_space",
    "library": "library",
    "study_cafe": "study_cafe",
}


def _query_to_google_types(query: PlaceQuery) -> list[str]:
    """Map PlaceQuery category + cuisine/dietary tags to Google place type IDs.

    Returns a deduplicated list ordered by specificity (category first, then tags).
    Only types with a known Google mapping are included — unrecognised tags are
    handled by the text query instead.
    """
    seen: set[str] = set()
    types: list[str] = []

    def _add(t: str) -> None:
        if t not in seen:
            seen.add(t)
            types.append(t)

    if query.category:
        gtype = _CATEGORY_TO_GOOGLE_TYPE.get(query.category.value)
        if gtype:
            _add(gtype)

    if query.tags:
        for tag_val in query.tags:
            gtype = _TAG_TO_GOOGLE_TYPE.get(str(tag_val))
            if gtype:
                _add(gtype)

    return types


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
        google_types = _query_to_google_types(query)
        if google_types:
            body["includedType"] = google_types[0]  # text search accepts one type
        if query.open_now is True:
            body["openNow"] = True
        if query.min_rating is not None:
            body["minRating"] = query.min_rating
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
        google_types = _query_to_google_types(query)
        if google_types:
            body["includedTypes"] = google_types
        if query.open_now is True:
            body["openNow"] = True
        if query.min_rating is not None:
            body["minRating"] = query.min_rating
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
