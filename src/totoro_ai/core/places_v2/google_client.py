"""GooglePlacesClient — Places API v1 adapter returning PlaceObject.

Both methods return PlaceObject with:
- provider_id = "google:{raw_place_id}"
- lat, lng, address populated from Google (become PlaceCore location fields)
- live fields (rating, hours, phone, website) populated (cache-only)
- cached_at = now()
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from .models import HoursDict, PlaceObject, PlaceQuery

logger = logging.getLogger(__name__)

_PLACES_API_BASE = "https://places.googleapis.com/v1/places"
_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.location,"
    "places.rating,"
    "places.regularOpeningHours,"
    "places.nationalPhoneNumber,"
    "places.websiteUri,"
    "places.types,"
    "places.userRatingCount,"
    "places.timeZone"
)

_DAY_INT_TO_NAME: dict[int, str] = {
    0: "sunday",
    1: "monday",
    2: "tuesday",
    3: "wednesday",
    4: "thursday",
    5: "friday",
    6: "saturday",
}


class GooglePlacesClient:
    def __init__(self, api_key: str, http: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._http = http

    async def text_search(
        self, query: PlaceQuery, limit: int = 20
    ) -> list[PlaceObject]:
        if not query.text:
            return []

        body: dict[str, Any] = {
            "textQuery": query.text,
            "maxResultCount": min(limit, 20),
        }

        return await self._post(":searchText", body, limit)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

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

        raw_places: list[dict[str, Any]] = data.get("places") or []
        now = datetime.now(UTC)
        result = []
        for raw in raw_places[:limit]:
            obj = _map_place(raw, now)
            if obj:
                result.append(obj)
        return result


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

def _map_place(raw: dict[str, Any], now: datetime) -> PlaceObject | None:
    raw_id = raw.get("id")
    if not raw_id:
        return None

    location = raw.get("location") or {}
    display_name = raw.get("displayName") or {}

    place_name = display_name.get("text") or ""
    if not place_name:
        return None

    return PlaceObject(
        provider_id=f"google:{raw_id}",
        place_name=place_name,
        lat=location.get("latitude"),
        lng=location.get("longitude"),
        address=raw.get("formattedAddress"),
        rating=raw.get("rating"),
        hours=_map_hours(raw),
        phone=raw.get("nationalPhoneNumber"),
        website=raw.get("websiteUri"),
        popularity=raw.get("userRatingCount"),
        cached_at=now,
    )


def _map_hours(raw: dict[str, Any]) -> HoursDict | None:
    opening_hours = raw.get("regularOpeningHours") or {}
    time_zone = raw.get("timeZone") or {}
    timezone_id = time_zone.get("id") if isinstance(time_zone, dict) else None
    periods = opening_hours.get("periods") or []
    if not periods or not timezone_id:
        return None

    hours: dict[str, Any] = {}
    for period in periods:
        open_obj = period.get("open") or {}
        close_obj = period.get("close")
        day_int = open_obj.get("day")
        if day_int is None or day_int not in _DAY_INT_TO_NAME:
            continue
        day_name = _DAY_INT_TO_NAME[day_int]
        if close_obj is None:
            hours[day_name] = ["00:00-00:00"]
        else:
            slot = f"{_fmt_clock(open_obj)}-{_fmt_clock(close_obj)}"
            hours.setdefault(day_name, []).append(slot)

    for day_name in _DAY_INT_TO_NAME.values():
        if day_name not in hours:
            hours[day_name] = []

    hours["timezone"] = timezone_id
    return hours


def _fmt_clock(clock: dict[str, Any]) -> str:
    hour = clock.get("hour")
    minute = clock.get("minute")
    h = hour if isinstance(hour, int) and 0 <= hour <= 23 else 0
    m = minute if isinstance(minute, int) and 0 <= minute <= 59 else 0
    return f"{h:02d}:{m:02d}"
