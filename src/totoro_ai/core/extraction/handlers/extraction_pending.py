"""ExtractionPendingHandler — background continuation for deferred extractions."""

from __future__ import annotations

import logging
from typing import Any

from totoro_ai.core.extraction.dedup import dedup_candidates
from totoro_ai.core.extraction.persistence import (
    ExtractionPersistenceService,
    PlaceSaveOutcome,
)
from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository
from totoro_ai.core.extraction.types import ExtractionPending
from totoro_ai.core.extraction.validator import PlacesValidatorProtocol

logger = logging.getLogger(__name__)


def _outcome_to_item_dict(outcome: PlaceSaveOutcome) -> dict[str, Any]:
    """Project one outcome into an `ExtractPlaceItem`-shaped dict.

    Same schema `ExtractionService.run()` emits synchronously; used by the
    background handler to write the final status to the cache so the
    product repo polls a shape-identical payload.
    """
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


def _build_status_payload(
    outcomes: list[PlaceSaveOutcome],
    event: ExtractionPending,
) -> dict[str, Any]:
    """Build the `ExtractPlaceResponse`-compatible status payload."""
    return {
        "results": [_outcome_to_item_dict(o) for o in outcomes],
        "source_url": event.url,
        "request_id": None,
    }


def _failed_payload(event: ExtractionPending) -> dict[str, Any]:
    """Single-item 'failed' payload when validation found nothing."""
    return {
        "results": [{"place": None, "confidence": None, "status": "failed"}],
        "source_url": event.url,
        "request_id": None,
    }


class ExtractionPendingHandler:
    """Handles ExtractionPending domain events dispatched by ExtractionPipeline."""

    def __init__(
        self,
        background_enrichers: list[Any],
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
            await self._status_repo.write(event.request_id, _failed_payload(event))
            return

        outcomes = await self._persistence.save_and_emit(results, event.user_id)

        payload = _build_status_payload(outcomes, event)
        await self._status_repo.write(event.request_id, payload)
