"""Places validator — parallel multi-candidate validation with confidence scoring."""

from __future__ import annotations

import asyncio
from typing import Protocol

from totoro_ai.core.config import ConfidenceConfig
from totoro_ai.core.extraction.confidence import calculate_confidence
from totoro_ai.core.extraction.places_client import PlacesClient, PlacesMatchQuality
from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionResult,
)

# Google Places types that indicate a geographic feature, not a venue.
# Candidates that resolve to any of these types are rejected post-validation.
_GEOGRAPHIC_PLACE_TYPES: frozenset[str] = frozenset(
    {
        "route",          # street or road
        "street_address", # specific address on a street
        "political",      # generic political entity
        "locality",       # city or town
        "sublocality",    # district or neighbourhood within a city
        "sublocality_level_1",
        "sublocality_level_2",
        "sublocality_level_3",
        "sublocality_level_4",
        "sublocality_level_5",
        "country",        # country
        "administrative_area_level_1",  # state / province
        "administrative_area_level_2",  # county / region
        "administrative_area_level_3",
        "administrative_area_level_4",
        "administrative_area_level_5",
        "neighborhood",   # neighbourhood
        "postal_code",
        "intersection",
        "premise",        # building/address, not a business venue
        "natural_feature",
    }
)


# Match-quality → modifier mapping (ADR-029, plan.md Phase 5)
_QUALITY_MODIFIERS: dict[PlacesMatchQuality, float] = {
    PlacesMatchQuality.EXACT: 1.0,
    PlacesMatchQuality.FUZZY: 0.9,
    PlacesMatchQuality.CATEGORY_ONLY: 0.8,
    PlacesMatchQuality.NONE: 0.3,
}


class PlacesValidatorProtocol(Protocol):
    """Protocol for swappable place-registry validators (ADR-038)."""

    async def validate(
        self, candidates: list[CandidatePlace]
    ) -> list[ExtractionResult] | None: ...


class GooglePlacesValidator:
    """Validates CandidatePlaces against Google Places in parallel.

    Returns a list of ExtractionResult with confidence scores, or None when
    no candidates survive validation.  One Places-API failure does not abort
    the batch — that candidate is silently dropped.
    """

    def __init__(
        self,
        places_client: PlacesClient,
        confidence_config: ConfidenceConfig,
    ) -> None:
        self._places_client = places_client
        self._confidence_config = confidence_config

    async def validate(
        self, candidates: list[CandidatePlace]
    ) -> list[ExtractionResult] | None:
        if not candidates:
            return None

        raw = await asyncio.gather(
            *[self._validate_one(c) for c in candidates],
            return_exceptions=True,
        )
        results = [r for r in raw if isinstance(r, ExtractionResult)]
        return results if results else None

    async def _validate_one(
        self, candidate: CandidatePlace
    ) -> ExtractionResult | None:
        try:
            places_match = await self._places_client.validate_place(
                name=candidate.name, location=candidate.city
            )
        except Exception:
            return None

        modifier = _QUALITY_MODIFIERS[places_match.match_quality]
        confidence = calculate_confidence(
            source=candidate.source,
            match_modifier=modifier,
            corroborated=candidate.corroborated,
            config=self._confidence_config,
            signals=candidate.signals or None,
        )

        if confidence == 0.0 or places_match.external_id is None:
            return None

        # Reject candidates whose Google Places types indicate a geographic
        # feature (street, district, city, country) rather than a venue.
        if _GEOGRAPHIC_PLACE_TYPES.intersection(places_match.place_types):
            return None

        return ExtractionResult(
            place_name=places_match.validated_name or candidate.name,
            address=None,  # formatted_address not in request_fields; deferred to Run 3
            city=candidate.city,
            cuisine=candidate.cuisine,
            confidence=confidence,
            resolved_by=candidate.source,
            corroborated=candidate.corroborated,
            external_provider=places_match.external_provider,
            external_id=places_match.external_id,
        )
