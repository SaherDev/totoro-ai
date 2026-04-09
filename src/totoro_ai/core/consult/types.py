"""Data types for the consult pipeline — candidates and mappers (ADR-049)."""

from typing import Any, Protocol

from pydantic import BaseModel, Field

from totoro_ai.api.schemas.recall import RecallResult


class Candidate(BaseModel):
    """Internal unified representation of a place under evaluation.

    Both saved and discovered places are normalized to this model before
    ranking and response building.
    """

    place_id: str
    place_name: str
    address: str
    cuisine: str | None = None
    price_range: str | None = None  # "low" | "mid" | "high" | None
    lat: float | None = None
    lng: float | None = None
    external_id: str | None = None
    source: str = Field(...)  # "saved" | "discovered"
    popularity_score: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Normalized rating 0.0–1.0"
    )
    # Taste signal dimensions — populated by ranking post-retrieval
    ambiance: str | None = None
    crowd_level: str | None = None
    time_of_day: str | None = None
    dietary_pref: str | None = None
    cuisine_frequency: str | None = None
    cuisine_adventurousness: str | None = None
    # Distance from search location in metres (computed post-retrieval)
    distance: float = 0.0


class CandidateMapper(Protocol):
    """Protocol for converting source objects to Candidate."""

    def map(self, source_object: Any) -> Candidate:
        """Convert source object to Candidate."""
        ...


class RecallResultToCandidateMapper:
    """Converts RecallResult (saved place) to Candidate (source="saved")."""

    def map(self, recall_result: RecallResult) -> Candidate:
        """Convert RecallResult to Candidate with source="saved".

        Distance is set to 0.0 at construction; ConsultService computes
        actual distance post-retrieval based on search_location.
        """
        return Candidate(
            place_id=recall_result.place_id,
            place_name=recall_result.place_name,
            address=recall_result.address,
            cuisine=recall_result.cuisine,
            price_range=recall_result.price_range,
            lat=recall_result.lat,
            lng=recall_result.lng,
            external_id=recall_result.external_id,
            source="saved",
            popularity_score=0.5,  # Default for saved places without ratings
            ambiance=None,
            crowd_level=None,
            time_of_day=None,
            dietary_pref=None,
            cuisine_frequency=None,
            cuisine_adventurousness=None,
            distance=0.0,
        )


class ExternalCandidateMapper:
    """Converts Google Places Nearby Search result to Candidate (source="discovered")."""

    @staticmethod
    def _map_price_level(price_level: int | None) -> str | None:
        """Map Google Places price_level (0-4) to canonical strings.

        0 → None (free or no price info)
        1, 2 → "low"
        3 → "mid"
        4 → "high"
        """
        if price_level is None:
            return None
        if price_level in (1, 2):
            return "low"
        if price_level == 3:
            return "mid"
        if price_level == 4:
            return "high"
        return None

    def map(self, google_result: dict[str, Any]) -> Candidate:
        """Convert Google Places Nearby Search result to Candidate (source="discovered").

        Args:
            google_result: Result dict from Google Places API with keys:
                place_id, name, vicinity, geometry, rating, price_level, types

        Returns:
            Candidate with source="discovered"
        """
        geometry = google_result.get("geometry", {})
        location = geometry.get("location", {})

        # Normalize rating (0.0–5.0) to 0.0–1.0
        rating = google_result.get("rating", 0.0)
        popularity_score = min(1.0, rating / 5.0) if rating else 0.5

        return Candidate(
            place_id=google_result["place_id"],
            place_name=google_result.get("name", ""),
            address=google_result.get("vicinity", ""),
            cuisine=None,  # Google Places doesn't return cuisine in Nearby Search
            price_range=self._map_price_level(google_result.get("price_level")),
            lat=location.get("lat"),
            lng=location.get("lng"),
            external_id=google_result.get("place_id"),
            source="discovered",
            popularity_score=popularity_score,
            ambiance=None,
            crowd_level=None,
            time_of_day=None,
            dietary_pref=None,
            cuisine_frequency=None,
            cuisine_adventurousness=None,
            distance=0.0,
        )
