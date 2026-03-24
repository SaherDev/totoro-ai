"""Google Places API client for place validation."""

import difflib
from enum import Enum
from typing import Protocol

import httpx
from pydantic import BaseModel

from totoro_ai.core.config import get_config, get_secrets


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


class PlacesClient(Protocol):
    """Protocol for place validation against an external database."""

    async def validate_place(
        self, name: str, location: str | None = None
    ) -> PlacesMatchResult:
        """Validate a place name and return match result."""
        ...


class GooglePlacesClient:
    """Google Places API client for place validation (ADR-022)."""

    def __init__(self) -> None:
        """Initialize with API key from config."""
        self.api_key = get_secrets().providers.google.api_key

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

        # Compute name similarity
        similarity = difflib.SequenceMatcher(
            None, name.lower(), matched_name.lower()
        ).ratio()

        if similarity >= 0.95:
            match_quality = PlacesMatchQuality.EXACT
        elif similarity >= 0.80:
            match_quality = PlacesMatchQuality.FUZZY
        else:
            match_quality = PlacesMatchQuality.CATEGORY_ONLY

        return PlacesMatchResult(
            match_quality=match_quality,
            validated_name=matched_name,
            external_provider="google",
            external_id=first_match.get("place_id"),
            lat=location_data.get("lat"),
            lng=location_data.get("lng"),
        )
