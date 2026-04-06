"""ExtractionPendingHandler — background continuation for deferred extractions."""

from __future__ import annotations

import logging
from typing import Any

from totoro_ai.core.extraction.dedup import dedup_candidates
from totoro_ai.core.extraction.persistence import ExtractionPersistenceService
from totoro_ai.core.extraction.types import ExtractionPending
from totoro_ai.core.extraction.validator import PlacesValidatorProtocol

logger = logging.getLogger(__name__)


class ExtractionPendingHandler:
    """Handles ExtractionPending domain events dispatched by ExtractionPipeline.

    Runs the three background enrichers in sequence, deduplicates, validates,
    and persists via ExtractionPersistenceService.
    """

    def __init__(
        self,
        background_enrichers: list[Any],  # list[Enricher] — Any for Protocol compat
        validator: PlacesValidatorProtocol,
        persistence: ExtractionPersistenceService,
    ) -> None:
        self._background_enrichers = background_enrichers
        self._validator = validator
        self._persistence = persistence

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
            return

        await self._persistence.save_and_emit(results, event.user_id)
