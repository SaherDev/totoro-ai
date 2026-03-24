"""Google Places API client for place validation."""

import difflib
import os
from enum import Enum
from typing import Protocol

import httpx
from pydantic import BaseModel

from totoro_ai.core.config import load_yaml_config


class PlacesMatchQuality(str, Enum):
    """Quality of match against Google Places database."""

    EXACT = "EXACT"                 # Name similarity ≥ 0.95
    FUZZY = "FUZZY"                 # Name similarity ≥ 0.80
    CATEGORY_ONLY = "CATEGORY_ONLY" # Place found, name similarity < 0.80
    NONE = "NONE"                   # No match found


class PlacesMatchResult(BaseModel):
    """Result of validating a place against Google Places."""

    match_quality: PlacesMatchQuality
    validated_name: str | None = None
    google_place_id: str | None = None
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
        """Initialize with API key from config or environment."""
        config = load_yaml_config(".local.yaml")

        # Try multiple paths in config (supports both .local.yaml and env-based structures)
        self.api_key = (
            config.get("google", {}).get("api_key")
            or config.get("providers", {}).get("google", {}).get("api_key")
            or ""
        )

        # If config is empty, try environment variable (Google convention)
        if not self.api_key:
            self.api_key = os.environ.get("GOOGLE_API_KEY") or ""

        if not self.api_key:
            raise ValueError(
                "Google Places API key not found. Set one of:\n"
                "  1. config/.local.yaml: google.api_key: YOUR_KEY\n"
                "  2. Environment: export GOOGLE_API_KEY=YOUR_KEY"
            )

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
        query = f"{name}"
        if location:
            query = f"{name} {location}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
                    params={
                        "input": query,
                        "inputtype": "textquery",
                        "fields": "name,formatted_address,place_id,geometry",
                        "key": self.api_key,
                    },
                    timeout=5.0,
                )
                response.raise_for_status()
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                raise RuntimeError(f"Google Places API error: {e}")

        data = response.json()

        if not data.get("candidates"):
            return PlacesMatchResult(match_quality=PlacesMatchQuality.NONE)

        first_match = data["candidates"][0]
        matched_name = first_match.get("name", "")
        geometry = first_match.get("geometry", {})
        location_data = geometry.get("location", {})

        # Compute name similarity
        similarity = difflib.SequenceMatcher(None, name.lower(), matched_name.lower()).ratio()

        if similarity >= 0.95:
            match_quality = PlacesMatchQuality.EXACT
        elif similarity >= 0.80:
            match_quality = PlacesMatchQuality.FUZZY
        else:
            match_quality = PlacesMatchQuality.CATEGORY_ONLY

        return PlacesMatchResult(
            match_quality=match_quality,
            validated_name=matched_name,
            google_place_id=first_match.get("place_id"),
            lat=location_data.get("lat"),
            lng=location_data.get("lng"),
        )
