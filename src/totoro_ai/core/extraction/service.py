"""Extraction service orchestrating the cascade pipeline."""

import logging

from totoro_ai.api.schemas.extract_place import ExtractPlaceResponse, SavedPlace
from totoro_ai.core.extraction.extraction_pipeline import ExtractionPipeline
from totoro_ai.core.extraction.input_parser import parse_input
from totoro_ai.core.extraction.persistence import ExtractionPersistenceService
from totoro_ai.core.extraction.types import ProvisionalResponse

logger = logging.getLogger(__name__)


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

        Args:
            raw_input: TikTok URL or plain text
            user_id: User identifier (validated by NestJS)

        Returns:
            ExtractPlaceResponse where every pipeline candidate appears in
            places with its own extraction_status ("saved", "duplicate",
            "below_threshold").

        Raises:
            ValueError: If raw_input is empty (→ 400)
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
                provisional=True,
                places=[],
                pending_levels=[level.value for level in result.pending_levels],
                extraction_status="processing",
                source_url=parsed.url,
                request_id=result.request_id or None,
            )

        outcomes = await self._persistence.save_and_emit(result, user_id)

        places = [
            SavedPlace(
                place_id=outcome.place_id,
                place_name=outcome.result.place_name,
                address=outcome.result.address,
                city=outcome.result.city,
                cuisine=outcome.result.cuisine,
                confidence=outcome.result.confidence,
                resolved_by=outcome.result.resolved_by.value,
                external_provider=outcome.result.external_provider,
                external_id=outcome.result.external_id,
                extraction_status=outcome.status,
            )
            for outcome in outcomes
        ]

        # Top-level status: "saved" if any saved, else dominant non-saved status
        statuses = {o.status for o in outcomes}
        if "saved" in statuses:
            top_status = "saved"
        elif "below_threshold" in statuses:
            top_status = "below_threshold"
        else:
            top_status = "duplicate"

        return ExtractPlaceResponse(
            provisional=False,
            places=places,
            pending_levels=[],
            extraction_status=top_status,
            source_url=parsed.url,
        )
