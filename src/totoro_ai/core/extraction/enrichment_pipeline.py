"""EnrichmentPipeline — sequences enrichers then deduplicates candidates."""

from __future__ import annotations

from totoro_ai.core.extraction.dedup import dedup_candidates
from totoro_ai.core.extraction.protocols import Enricher
from totoro_ai.core.extraction.types import ExtractionContext


class EnrichmentPipeline:
    """Runs a list of Enrichers in sequence, then deduplicates candidates.

    Each enricher mutates context in place (appending candidates, setting
    caption/transcript).  After all enrichers complete, dedup_candidates
    collapses same-name candidates and marks corroborated winners.
    """

    def __init__(self, enrichers: list[Enricher]) -> None:
        self._enrichers = enrichers

    async def run(self, context: ExtractionContext) -> None:
        for enricher in self._enrichers:
            await enricher.enrich(context)
        dedup_candidates(context)
