"""Extraction service orchestrating the cascade pipeline."""

import asyncio
import logging
from typing import Any
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
from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository
from totoro_ai.core.places import PlaceSource

logger = logging.getLogger(__name__)


def _source_from_url(url: str | None) -> PlaceSource | None:
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


def _outcome_to_dict(outcome: PlaceSaveOutcome) -> dict[str, Any]:
    if outcome.status == "below_threshold":
        return {
            "place": None,
            "confidence": outcome.metadata.confidence,
            "status": "failed",
        }
    place = outcome.place
    return {
        "place": place.model_dump(mode="json") if place else None,
        "confidence": outcome.metadata.confidence,
        "status": outcome.status,
    }


class ExtractionService:
    """Orchestrate place extraction cascade pipeline (ADR-008, ADR-034)."""

    def __init__(
        self,
        pipeline: ExtractionPipeline,
        persistence: ExtractionPersistenceService,
        status_repo: ExtractionStatusRepository,
    ) -> None:
        self._pipeline = pipeline
        self._persistence = persistence
        self._status_repo = status_repo

    async def run(self, raw_input: str, user_id: str) -> ExtractPlaceResponse:
        """Return pending immediately and run the full pipeline as a background task."""
        if not raw_input or not raw_input.strip():
            raise ValueError("raw_input cannot be empty")

        parsed = parse_input(raw_input)
        source = _source_from_url(parsed.url)
        request_id = uuid4().hex

        asyncio.create_task(
            self._run_background(
                url=parsed.url,
                supplementary_text=parsed.supplementary_text,
                user_id=user_id,
                source=source,
                request_id=request_id,
            )
        )
        return ExtractPlaceResponse(
            results=[ExtractPlaceItem(place=None, confidence=None, status="pending")],
            source_url=parsed.url,
            request_id=request_id,
        )

    async def _run_background(
        self,
        url: str | None,
        supplementary_text: str,
        user_id: str,
        source: PlaceSource | None,
        request_id: str,
    ) -> None:
        try:
            result = await self._pipeline.run(
                url=url,
                user_id=user_id,
                supplementary_text=supplementary_text,
            )
            if not result:
                await self._status_repo.write(
                    request_id,
                    {
                        "results": [
                            {"place": None, "confidence": None, "status": "failed"}
                        ],
                        "source_url": url,
                        "request_id": None,
                    },
                )
                return
            outcomes = await self._persistence.save_and_emit(
                result, user_id, source_url=url, source=source
            )
            await self._status_repo.write(
                request_id,
                {
                    "results": [_outcome_to_dict(o) for o in outcomes],
                    "source_url": url,
                    "request_id": None,
                },
            )
        except Exception:
            logger.exception("Background extraction failed for request %s", request_id)
