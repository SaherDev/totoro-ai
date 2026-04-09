"""Places module — place validation and discovery abstraction (ADR-049)."""

from totoro_ai.core.places.places_client import (
    GooglePlacesClient,
    PlacesClient,
    PlacesMatchQuality,
    PlacesMatchResult,
)

__all__ = [
    "PlacesClient",
    "GooglePlacesClient",
    "PlacesMatchResult",
    "PlacesMatchQuality",
]
