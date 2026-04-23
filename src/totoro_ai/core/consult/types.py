"""Consult pipeline types — PlaceObject-based (ADR-054, feature 019).

Every "place" flowing between LangGraph nodes is a `PlaceObject`. The ranker
wraps places in `ScoredPlace` for the short window where scores travel
alongside the place; the consult service unwraps them back to `PlaceObject`
before building the response.

External provider results (Google Places Nearby Search) are mapped to
`PlaceObject` via `map_google_place_to_place_object` so the pipeline has one
shape end-to-end.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from totoro_ai.core.places.models import (
    PlaceAttributes,
    PlaceObject,
    PlaceType,
)
from totoro_ai.core.places.places_client import PlacesMatchResult

logger = logging.getLogger(__name__)


# Google Places "types" array → PlaceType.
# Longer per-category lists are preferred over one-off aliases so that any
# near-equivalent string still routes to the right bucket. Checked in the
# order below so a venue tagged both `restaurant` and `store` lands as
# food_and_drink (the more specific food signal wins).
_GOOGLE_TYPE_TO_PLACE_TYPE: dict[str, PlaceType] = {
    # --- food_and_drink ---
    "restaurant": PlaceType.food_and_drink,
    "cafe": PlaceType.food_and_drink,
    "bar": PlaceType.food_and_drink,
    "bakery": PlaceType.food_and_drink,
    "meal_takeaway": PlaceType.food_and_drink,
    "meal_delivery": PlaceType.food_and_drink,
    "food": PlaceType.food_and_drink,
    "night_club": PlaceType.food_and_drink,
    # --- things_to_do ---
    "museum": PlaceType.things_to_do,
    "park": PlaceType.things_to_do,
    "tourist_attraction": PlaceType.things_to_do,
    "aquarium": PlaceType.things_to_do,
    "zoo": PlaceType.things_to_do,
    "art_gallery": PlaceType.things_to_do,
    "amusement_park": PlaceType.things_to_do,
    "stadium": PlaceType.things_to_do,
    "movie_theater": PlaceType.things_to_do,
    # --- shopping ---
    "store": PlaceType.shopping,
    "shopping_mall": PlaceType.shopping,
    "book_store": PlaceType.shopping,
    "clothing_store": PlaceType.shopping,
    "shoe_store": PlaceType.shopping,
    "jewelry_store": PlaceType.shopping,
    "department_store": PlaceType.shopping,
    "supermarket": PlaceType.shopping,
    # --- accommodation ---
    "lodging": PlaceType.accommodation,
    # --- services ---
    "gym": PlaceType.services,
    "spa": PlaceType.services,
    "beauty_salon": PlaceType.services,
    "hair_care": PlaceType.services,
    "pharmacy": PlaceType.services,
    "laundry": PlaceType.services,
    "post_office": PlaceType.services,
    "bank": PlaceType.services,
}


def _google_types_to_place_type(types: list[str]) -> PlaceType:
    """Map a Google `types[]` array to a canonical `PlaceType`.

    Scans the list in order — the first known type wins. Defaults to
    `PlaceType.services` and emits a `google_place_type_unknown` log line
    when no known type is present so we can spot coverage gaps.
    """
    for google_type in types:
        mapped = _GOOGLE_TYPE_TO_PLACE_TYPE.get(google_type)
        if mapped is not None:
            return mapped
    logger.info("google_place_type_unknown", extra={"types": list(types)})
    return PlaceType.services


class NoMatchesError(Exception):
    """Raised by ConsultService when no candidates survive the pipeline."""


def map_google_place_to_place_object(google_result: dict[str, Any]) -> PlaceObject:
    """Build a transient `PlaceObject` from a Google Places Nearby Search result.

    These places are NOT persisted — they're consult-only candidates that
    flow through ranking and the response. `place_id` is a synthetic UUID so
    the object satisfies `PlaceObject` invariants; it is never written to
    the DB in this code path.
    """
    geometry = google_result.get("geometry") or {}
    location = geometry.get("location") or {}
    lat = location.get("lat")
    lng = location.get("lng")

    price_level = google_result.get("price_level")
    price_hint = _map_google_price_level(price_level)

    rating = google_result.get("rating")
    popularity = min(1.0, rating / 5.0) if isinstance(rating, int | float) else None

    provider_id = (
        f"google:{google_result['place_id']}" if google_result.get("place_id") else None
    )

    place_type = _google_types_to_place_type(google_result.get("types") or [])

    return PlaceObject(
        place_id=str(uuid4()),
        place_name=google_result.get("name", ""),
        place_type=place_type,
        attributes=PlaceAttributes(price_hint=price_hint),
        provider_id=provider_id,
        lat=lat,
        lng=lng,
        address=google_result.get("vicinity"),
        rating=rating if isinstance(rating, int | float) else None,
        popularity=popularity,
        geo_fresh=lat is not None and lng is not None,
    )


def map_match_result_to_place_object(result: PlacesMatchResult) -> PlaceObject:
    """Build a transient PlaceObject from a validated PlacesMatchResult.

    Used by the place_suggestions path — agent-suggested names that passed
    EXACT or FUZZY validation. Not persisted; synthetic place_id only.
    """
    provider_id = (
        f"{result.external_provider}:{result.external_id}"
        if result.external_id
        else None
    )
    return PlaceObject(
        place_id=str(uuid4()),
        place_name=result.validated_name or "",
        place_type=PlaceType.services,
        attributes=PlaceAttributes(),
        provider_id=provider_id,
        lat=result.lat,
        lng=result.lng,
        address=result.address,
        geo_fresh=result.lat is not None and result.lng is not None,
    )


def _map_google_price_level(price_level: int | None) -> str | None:
    """Google Places price_level (0-4) → canonical price_hint.

    0          → None (free / unknown)
    1, 2       → "cheap"   (equivalent to legacy "low")
    3          → "moderate" (equivalent to legacy "mid")
    4          → "expensive" (equivalent to legacy "high")
    """
    if price_level is None:
        return None
    if price_level in (1, 2):
        return "cheap"
    if price_level == 3:
        return "moderate"
    if price_level == 4:
        return "expensive"
    return None
