"""Extraction service orchestrating the cascade pipeline."""

import logging
from uuid import uuid4

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
from totoro_ai.core.places import PlaceSource

logger = logging.getLogger(__name__)


def _source_from_url(url: str | None) -> PlaceSource | None:
    """Map a URL to the canonical `PlaceSource` value.

    - tiktok.com        → PlaceSource.tiktok
    - instagram.com     → PlaceSource.instagram
    - youtube.com/youtu.be → PlaceSource.youtube
    - any other http(s) → PlaceSource.link
    - None (plain text) → None (the save tool leaves source unset)
    """
    if url is None:
        return None
    lowered = url.lower()
    if "tiktok.com" in lowered:
        return PlaceSource.tiktok
    if "instagram.com" in lowered:
        return PlaceSource.instagram
    if "youtube.com" in lowered or "youtu.be" in lowered:
        return PlaceSource.youtube
    return PlaceSource.link


def _outcome_to_item(outcome: PlaceSaveOutcome) -> ExtractPlaceItem:
    """Project one `PlaceSaveOutcome` into an `ExtractPlaceItem`.

    Below-threshold outcomes carry the validator confidence (so the caller
    can see how close the cascade got) but `place` stays `None` and status
    collapses to "failed" — the row was never written to the permanent
    store.

    "needs_review" passes through unchanged: the row was written and the
    place is set, but the UI should prompt the user to confirm the match
    (ADR-057).
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

        Generates a `request_id` at the top so every response — saved,
        pending, or failed — carries the same correlation id. The ID is
        used for Langfuse traces, log joins, and the pending-status polling
        cache. Pending responses inherit the pipeline's own request_id when
        present (the background handler keyed the status cache on it) and
        fall back to the freshly-generated one otherwise.

        Returns an `ExtractPlaceResponse` whose `results` list has one
        `ExtractPlaceItem` per outcome of the cascade:

        - one "saved" / "needs_review" / "duplicate" item per successful
          validation
        - one "failed" item when nothing resolves or confidence is below
          `save_threshold`
        - one "pending" item when the pipeline dispatched background
          enrichers (caller polls via `request_id`)
        """
        if not raw_input or not raw_input.strip():
            raise ValueError("raw_input cannot be empty")

        parsed = parse_input(raw_input)
        source = _source_from_url(parsed.url)
        request_id = uuid4().hex

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
                request_id=result.request_id or request_id,
            )

        if not result:
            return ExtractPlaceResponse(
                results=[
                    ExtractPlaceItem(place=None, confidence=None, status="failed")
                ],
                source_url=parsed.url,
                request_id=request_id,
            )

        outcomes = await self._persistence.save_and_emit(
            result,
            user_id,
            source_url=parsed.url,
            source=source,
        )
        items = [_outcome_to_item(o) for o in outcomes]

        return ExtractPlaceResponse(
            results=items,
            source_url=parsed.url,
            request_id=request_id,
        )
