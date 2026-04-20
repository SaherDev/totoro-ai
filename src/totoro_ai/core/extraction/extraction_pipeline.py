"""ExtractionPipeline — three-phase runner for the extraction cascade."""

from __future__ import annotations

from totoro_ai.core.config import ExtractionConfig
from totoro_ai.core.extraction.dedup import (
    dedup_candidates,
    dedup_validated_by_provider_id,
)
from totoro_ai.core.extraction.enrichment_pipeline import EnrichmentPipeline
from totoro_ai.core.extraction.protocols import Enricher
from totoro_ai.core.extraction.types import (
    ExtractionContext,
    ValidatedCandidate,
)
from totoro_ai.core.extraction.validator import PlacesValidatorProtocol


class ExtractionPipeline:
    """Three-phase extraction runner (ADR-008 — sequential async, not LangGraph).

    Phase 1: Inline enrichment (emoji regex, LLM NER, oEmbed, yt-dlp metadata)
             via EnrichmentPipeline, which also deduplicates candidates.
    Phase 2: Validate candidates against Google Places; return immediately on success.
    Phase 3: No inline candidates → run background enrichers (subtitle, whisper,
             vision) inline, re-validate, return results. Always returns synchronously.
    """

    def __init__(
        self,
        enrichment: EnrichmentPipeline,
        validator: PlacesValidatorProtocol,
        background_enrichers: list[Enricher],
        extraction_config: ExtractionConfig,
    ) -> None:
        self._enrichment = enrichment
        self._validator = validator
        self._background_enrichers = background_enrichers
        self._extraction_config = extraction_config

    async def run(
        self,
        url: str | None,
        user_id: str,
        supplementary_text: str = "",
    ) -> list[ValidatedCandidate]:
        context = ExtractionContext(
            url=url,
            user_id=user_id,
            supplementary_text=supplementary_text,
        )

        # Phase 1: inline enrichment + dedup
        await self._enrichment.run(context)

        # Phase 2: validate candidates, then dedup by provider_id
        results = await self._validator.validate(context.candidates)
        if results:
            return dedup_validated_by_provider_id(
                results, self._extraction_config.confidence
            )

        # Phase 3 only fires for URL inputs — background enrichers (subtitle,
        # whisper, vision) all require a video/page URL to process.
        if url is None:
            return []

        # Phase 3: run background enrichers inline, re-validate
        for enricher in self._background_enrichers:
            await enricher.enrich(context)
        dedup_candidates(context)

        results = await self._validator.validate(context.candidates)
        if results:
            return dedup_validated_by_provider_id(
                results, self._extraction_config.confidence
            )
        return []
