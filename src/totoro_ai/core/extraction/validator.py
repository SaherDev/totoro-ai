"""Google Places validator — Phase 2 of the extraction pipeline.

NOT an enricher. Separate interface. Takes candidates explicitly,
validates each in parallel, returns list[ExtractionResult] or None.
"""

import asyncio
import logging

from totoro_ai.core.config import ConfidenceWeights
from totoro_ai.core.extraction.confidence import compute_confidence
from totoro_ai.core.extraction.models import CandidatePlace
from totoro_ai.core.extraction.places_client import PlacesClient
from totoro_ai.core.extraction.result import ExtractionResult

logger = logging.getLogger(__name__)


class GooglePlacesValidator:
    """Validate candidates against Google Places API (ADR-041).

    Validates each candidate independently in parallel via asyncio.gather.
    Returns list[ExtractionResult] if any validated, None otherwise.
    """

    def __init__(
        self,
        places_client: PlacesClient,
        confidence_weights: ConfidenceWeights,
    ) -> None:
        self._places_client = places_client
        self._confidence_weights = confidence_weights

    async def validate(
        self,
        candidates: list[CandidatePlace],
        source_url: str | None = None,
    ) -> list[ExtractionResult] | None:
        if not candidates:
            return None

        tasks = [self._validate_one(candidate, source_url) for candidate in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        validated: list[ExtractionResult] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Validation failed for candidate '%s': %s",
                    candidates[i].name,
                    result,
                )
            elif result is not None:
                validated.append(result)

        return validated if validated else None

    async def _validate_one(
        self,
        candidate: CandidatePlace,
        source_url: str | None,
    ) -> ExtractionResult | None:
        location = candidate.city
        match = await self._places_client.validate_place(
            name=candidate.name,
            location=location,
        )

        confidence = compute_confidence(
            source=candidate.source,
            match_quality=match.match_quality,
            weights=self._confidence_weights,
            corroborated=candidate.corroborated,
        )

        return ExtractionResult(
            place_name=match.validated_name or candidate.name,
            address=None,
            city=candidate.city,
            cuisine=candidate.cuisine,
            confidence=round(confidence, 2),
            resolved_by=candidate.source,
            corroborated=candidate.corroborated,
            external_provider=match.external_provider,
            external_id=match.external_id,
            source_url=source_url,
        )
