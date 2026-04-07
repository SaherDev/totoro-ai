"""ExtractionPendingHandler — background continuation for deferred extractions."""

from __future__ import annotations

import logging
from typing import Any

from totoro_ai.core.extraction.dedup import dedup_candidates
from totoro_ai.core.extraction.persistence import ExtractionPersistenceService
from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository
from totoro_ai.core.extraction.types import ExtractionPending, ExtractionResult
from totoro_ai.core.extraction.validator import PlacesValidatorProtocol

logger = logging.getLogger(__name__)


def _build_status_payload(
    results: list[ExtractionResult],
    saved_ids: list[str],
    event: ExtractionPending,
) -> dict[str, Any]:
    """Build ExtractPlaceResponse-compatible dict for cache storage."""
    places = [
        {
            "place_id": pid,
            "place_name": r.place_name,
            "address": r.address,
            "city": r.city,
            "cuisine": r.cuisine,
            "confidence": r.confidence,
            "resolved_by": r.resolved_by.value,
            "external_provider": r.external_provider,
            "external_id": r.external_id,
        }
        for pid, r in zip(saved_ids, results, strict=False)
    ]
    return {
        "provisional": False,
        "places": places,
        "pending_levels": [],
        "extraction_status": "saved" if places else "duplicate",
        "source_url": event.url,
        "request_id": None,
    }


class ExtractionPendingHandler:
    """Handles ExtractionPending domain events dispatched by ExtractionPipeline.

    Runs the three background enrichers in sequence, deduplicates, validates,
    persists via ExtractionPersistenceService, and writes final status to cache
    so the product repo can poll for results via GET /v1/extract-place/status/{id}.
    """

    def __init__(
        self,
        background_enrichers: list[Any],  # list[Enricher] — Any for Protocol compat
        validator: PlacesValidatorProtocol,
        persistence: ExtractionPersistenceService,
        status_repo: ExtractionStatusRepository,
    ) -> None:
        self._background_enrichers = background_enrichers
        self._validator = validator
        self._persistence = persistence
        self._status_repo = status_repo

    async def handle(self, event: ExtractionPending) -> None:
        context = event.context

        for enricher in self._background_enrichers:
            await enricher.enrich(context)

        dedup_candidates(context)

        results = await self._validator.validate(context.candidates)
        if not results:
            logger.warning(
                "Background extraction found nothing for user %s", event.user_id
            )
            await self._status_repo.write(
                event.request_id, {"extraction_status": "failed"}
            )
            return

        saved_ids = await self._persistence.save_and_emit(results, event.user_id)

        payload = _build_status_payload(results, saved_ids, event)
        await self._status_repo.write(event.request_id, payload)
