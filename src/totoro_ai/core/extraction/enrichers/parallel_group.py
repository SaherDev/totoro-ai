"""Parallel enricher group — runs multiple enrichers concurrently."""

import asyncio
import logging

from totoro_ai.core.extraction.models import ExtractionContext
from totoro_ai.core.extraction.protocols import Enricher

logger = logging.getLogger(__name__)


class ParallelEnricherGroup:
    """Runs all enrichers in parallel via asyncio.gather.

    Every enricher runs to completion — no cancel-on-success logic.
    Exceptions from individual enrichers are logged but do not prevent
    other enrichers from completing.
    """

    def __init__(self, enrichers: list[Enricher]) -> None:
        self._enrichers = enrichers

    async def enrich(self, context: ExtractionContext) -> None:
        results = await asyncio.gather(
            *(enricher.enrich(context) for enricher in self._enrichers),
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Enricher %s raised %s in parallel group",
                    type(self._enrichers[i]).__name__,
                    result,
                    exc_info=result,
                )
