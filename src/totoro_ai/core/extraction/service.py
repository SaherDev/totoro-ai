"""Extraction service orchestrating the cascade pipeline."""

import logging

from totoro_ai.api.schemas.extract_place import (
    ExtractPlaceItem,
    ExtractPlaceResponse,
)
from totoro_ai.core.extraction.extraction_pipeline import ExtractionPipeline
from totoro_ai.core.extraction.input_parser import parse_input
from totoro_ai.core.extraction.persistence import (
    ExtractionPersistenceService,
    PlaceSaveOutcome,
)
from totoro_ai.core.extraction.types import ProvisionalResponse

logger = logging.getLogger(__name__)


def _outcome_to_item(outcome: PlaceSaveOutcome) -> ExtractPlaceItem:
    """Project one `PlaceSaveOutcome` into an `ExtractPlaceItem`.

    Below-threshold outcomes carry the validator confidence (so the caller
    can see how close the cascade got) but `place` stays `None` and status
    collapses to "failed" — the row was never written to the permanent
    store.
    """
    if outcome.status == "below_threshold":
        return ExtractPlaceItem(
            place=None,
            confidence=outcome.metadata.confidence,
            status="failed",
        )
    return ExtractPlaceItem(
        place=outcome.place,
        confidence=outcome.metadata.confidence,
        status=outcome.status,
    )


class ExtractionService:
    """Orchestrate place extraction cascade pipeline (ADR-008, ADR-034)."""

    def __init__(
        self,
        pipeline: ExtractionPipeline,
        persistence: ExtractionPersistenceService,
    ) -> None:
        self._pipeline = pipeline
        self._persistence = persistence

    async def run(self, raw_input: str, user_id: str) -> ExtractPlaceResponse:
        """Extract places from raw input and persist them.

        Returns an `ExtractPlaceResponse` whose `results` list has one
        `ExtractPlaceItem` per outcome of the cascade:

        - one "saved" / "duplicate" item per successful validation
        - one "failed" item when nothing resolves or confidence is below
          threshold
        - one "pending" item when the pipeline dispatched background
          enrichers (caller polls via `request_id`)
        """
        if not raw_input or not raw_input.strip():
            raise ValueError("raw_input cannot be empty")

        parsed = parse_input(raw_input)

        result = await self._pipeline.run(
            url=parsed.url,
            user_id=user_id,
            supplementary_text=parsed.supplementary_text,
        )

        if isinstance(result, ProvisionalResponse):
            return ExtractPlaceResponse(
                results=[
                    ExtractPlaceItem(place=None, confidence=None, status="pending")
                ],
                source_url=parsed.url,
                request_id=result.request_id or None,
            )

        if not result:
            return ExtractPlaceResponse(
                results=[
                    ExtractPlaceItem(place=None, confidence=None, status="failed")
                ],
                source_url=parsed.url,
            )

        outcomes = await self._persistence.save_and_emit(result, user_id)
        items = [_outcome_to_item(o) for o in outcomes]

        return ExtractPlaceResponse(
            results=items,
            source_url=parsed.url,
        )
