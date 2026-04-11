"""Google Places API client for place validation and discovery."""

import difflib
import re
from enum import Enum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from totoro_ai.core.config import get_config, get_secrets


def _normalize(text: str) -> str:
    """Lowercase and strip punctuation for name comparison.

    The LLM returns structured output with name and city as separate fields,
    so no location-noise filtering is needed — just basic normalization.
    Returns "" for strings shorter than 4 non-space characters (too short
    to compare meaningfully).
    """
    normalized = re.sub(r"[^\w\s]", "", text.lower()).strip()
    if len(normalized.replace(" ", "")) < 4:
        return ""
    return normalized


class PlacesMatchQuality(str, Enum):
    """Quality of match against Google Places database."""

    EXACT = "EXACT"  # Name similarity ≥ 0.95
    FUZZY = "FUZZY"  # Name similarity ≥ 0.80
    CATEGORY_ONLY = "CATEGORY_ONLY"  # Place found, name similarity < 0.80
    NONE = "NONE"  # No match found


class PlacesMatchResult(BaseModel):
    """Result of validating a place against Google Places."""

    match_quality: PlacesMatchQuality
    validated_name: str | None = None
    external_provider: str = "google"  # set by the client implementation
    external_id: str | None = None  # provider's own ID for the place
    lat: float | None = None
    lng: float | None = None
    place_types: list[str] = []  # Google Places 'types' (e.g. ["restaurant", "food"])


class PlacesClient(Protocol):
    """Protocol for place validation, discovery, and validation against external database."""

    async def validate_place(
        self, name: str, location: str | None = None
    ) -> PlacesMatchResult:
        """Validate a place name and return match result."""
        ...

    async def discover(
        self, search_location: dict[str, float], filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Discover places near a location using Nearby Search.

        Args:
            search_location: {"lat": float, "lng": float}
            filters: {"opennow": bool, "type": str, "keyword": str, ...}

        Returns:
            List of place result dicts from Google Places API
        """
        ...

    async def validate(self, candidate: Any, filters: dict[str, Any]) -> bool:
        """Validate a candidate place against filter constraints.

        Args:
            candidate: Candidate object with lat, lng, place_id, place_name
            filters: {"opennow": bool, ...}

        Returns:
            True if candidate passes all constraints, False otherwise
        """
        ...

    async def geocode(
        self,
        place_name: str,
        location_bias: dict[str, float] | None = None,
    ) -> dict[str, float] | None:
        """Resolve a place name to coordinates.

        Args:
            place_name: Place name to geocode
            location_bias: Optional {'lat': float, 'lng': float} to bias results

        Returns:
            {'lat': float, 'lng': float} or None if not found or on failure
        """
        ...


class GooglePlacesClient:
    """Google Places API client for place validation, discovery, and validation (ADR-049, ADR-022)."""

    def __init__(self) -> None:
        """Initialize with API key from config."""
        self.api_key = get_secrets().GOOGLE_API_KEY

        if not self.api_key:
            raise ValueError("Google API key not configured")

    async def validate_place(
        self, name: str, location: str | None = None
    ) -> PlacesMatchResult:
        """
        Validate place name against Google Places using Text Search API.

        Args:
            name: Place name to validate
            location: Optional location/address context

        Returns:
            PlacesMatchResult with match quality and details

        """
        config = get_config()
        places_config = config.external_services.google_places

        query = f"{name}"
        if location:
            query = f"{name} {location}"

        # Build fields parameter from config
        fields = ",".join(places_config.request_fields)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    places_config.base_url,
                    params={
                        "input": query,
                        "inputtype": "textquery",
                        "fields": fields,
                        "key": self.api_key,
                        "region": places_config.default_region,
                    },
                    timeout=places_config.timeout_seconds,
                )
                response.raise_for_status()
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                raise RuntimeError(f"Google Places API error: {e}") from e

        data = response.json()

        if not data.get("candidates"):
            return PlacesMatchResult(match_quality=PlacesMatchQuality.NONE)

        first_match = data["candidates"][0]
        matched_name = first_match.get("name", "")
        geometry = first_match.get("geometry", {})
        location_data = geometry.get("location", {})

        core_candidate = _normalize(name)
        core_google = _normalize(matched_name)

        similarity = difflib.SequenceMatcher(None, core_candidate, core_google).ratio()

        if similarity >= 0.85:
            match_quality = PlacesMatchQuality.EXACT
        elif similarity >= 0.70:
            match_quality = PlacesMatchQuality.FUZZY
        elif similarity >= 0.35:
            # Google found a result but the names diverge significantly.
            # Ratios below 0.35 indicate the candidate and result share almost
            # no token structure (e.g. "xyzzy" vs "fyzz gastropub" → 0.32) and
            # should be classified NONE, not CATEGORY_ONLY.
            match_quality = PlacesMatchQuality.CATEGORY_ONLY
        else:
            match_quality = PlacesMatchQuality.NONE

        return PlacesMatchResult(
            match_quality=match_quality,
            validated_name=matched_name,
            external_provider="google",
            external_id=first_match.get("place_id"),
            lat=location_data.get("lat"),
            lng=location_data.get("lng"),
            place_types=first_match.get("types", []),
        )

    async def discover(
        self, search_location: dict[str, float], filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Discover places near a location using Google Places Nearby Search.

        Args:
            search_location: {"lat": float, "lng": float}
            filters: {"opennow": bool, "type": str, "keyword": str, ...}

        Returns:
            List of place result dicts from Google Places API

        """
        config = get_config()
        places_config = config.external_services.google_places

        # Build request parameters
        params: dict[str, Any] = {
            "location": f"{search_location['lat']},{search_location['lng']}",
            "key": self.api_key,
        }

        # Add radius — fallback to config default if not in filters
        params["radius"] = (
            filters.get("radius") or get_config().consult.radius_defaults.default
        )

        # Add open_now if present
        if filters.get("opennow"):
            params["opennow"] = "true"

        # Add type if present
        if "type" in filters:
            params["type"] = filters["type"]

        # Add keyword if present
        if "keyword" in filters:
            params["keyword"] = filters["keyword"]

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    places_config.nearbysearch_url,
                    params=params,
                    timeout=places_config.timeout_seconds,
                )
                response.raise_for_status()
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                raise RuntimeError(f"Google Places Nearby Search API error: {e}") from e

        data = response.json()
        return data.get("results", [])

    async def geocode(
        self,
        place_name: str,
        location_bias: dict[str, float] | None = None,
    ) -> dict[str, float] | None:
        """Resolve a place name to coordinates using the Places Text Search API.

        Reuses the findplacefromtext endpoint — same URL and auth as validate_place.
        When location_bias is provided, results are biased toward that area
        (e.g., "Sukhumvit" resolves to Bangkok instead of Rayong).
        Returns {'lat': float, 'lng': float} or None on failure or no results.
        """
        config = get_config()
        places_config = config.external_services.google_places

        params: dict[str, Any] = {
            "input": place_name,
            "inputtype": "textquery",
            "fields": "geometry",
            "key": self.api_key,
            "region": places_config.default_region,
        }
        if location_bias:
            params["locationbias"] = (
                f"circle:50000@{location_bias['lat']},{location_bias['lng']}"
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    places_config.base_url,
                    params=params,
                    timeout=places_config.timeout_seconds,
                )
                response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException):
            return None

        data = response.json()
        candidates = data.get("candidates")
        if not candidates:
            return None

        location = candidates[0].get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")
        if lat is None or lng is None:
            return None

        return {"lat": float(lat), "lng": float(lng)}

    async def validate(self, candidate: Any, filters: dict[str, Any]) -> bool:
        """
        Validate a candidate place against filter constraints.

        Currently supports: opennow constraint via Nearby Search.

        Args:
            candidate: Candidate object with lat, lng, place_id, place_name
            filters: {"opennow": bool, ...}

        Returns:
            True if candidate passes all constraints, False otherwise

        """
        # If no constraints, candidate passes
        if not filters:
            return True

        # If opennow is required, re-query the Nearby Search to verify
        if filters.get("opennow"):
            results = await self.discover(
                {"lat": candidate.lat, "lng": candidate.lng},
                {"opennow": True, "keyword": candidate.place_name},
            )
            # Check if this place_id appears in the opennow results
            return any(r.get("place_id") == candidate.place_id for r in results)

        return True
