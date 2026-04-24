"""ExtractionPipeline — three-phase runner for the extraction cascade."""

from __future__ import annotations

from totoro_ai.core.config import ExtractionConfig
from totoro_ai.core.emit import EmitFn
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

_ENRICHER_LABELS = {
    "SubtitleCheckEnricher": "subtitles",
    "WhisperAudioEnricher": "audio transcript",
    "VisionFramesEnricher": "video frames",
    "TikTokOEmbedEnricher": "TikTok metadata",
    "YtDlpMetadataEnricher": "video metadata",
    "LLMNEREnricher": "text analysis",
    "CircuitBreakerEnricher": "fallback extractor",
    "ParallelEnricherGroup": "parallel extractors",
}


def _friendly(class_name: str) -> str:
    return _ENRICHER_LABELS.get(class_name, class_name)


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
        emit: EmitFn | None = None,
    ) -> list[ValidatedCandidate]:
        _emit: EmitFn = emit or (lambda _s, _m, _d=None: None)

        context = ExtractionContext(
            url=url,
            user_id=user_id,
            supplementary_text=supplementary_text,
        )

        # Phase 1: inline enrichment + dedup
        await self._enrichment.run(context)
        _emit(
            "save.enrich",
            f"Found {len(context.candidates)} possible place(s) in the text"
            if context.candidates
            else "No places found in the text",
        )

        # Phase 2: validate candidates, then dedup by provider_id
        results = await self._validator.validate(context.candidates)
        if results:
            _emit(
                "save.validate",
                f"Confirmed {len(results)} place(s) via Google Places",
            )
            return dedup_validated_by_provider_id(
                results, self._extraction_config.confidence
            )

        # Phase 3 only fires for URL inputs — background enrichers (subtitle,
        # whisper, vision) all require a video/page URL to process.
        if url is None:
            return []

        # Phase 3: run background enrichers inline, re-validate
        enrichers_fired: list[str] = []
        for enricher in self._background_enrichers:
            await enricher.enrich(context)
            enrichers_fired.append(type(enricher).__name__)
        dedup_candidates(context)
        _emit(
            "save.deep_enrichment",
            "Taking a closer look: " + ", ".join(_friendly(n) for n in enrichers_fired)
            if enrichers_fired
            else "No extra checks needed",
        )

        results = await self._validator.validate(context.candidates)
        validated_count = len(results) if results else 0
        _emit(
            "save.validate",
            f"Confirmed {validated_count} place(s) via Google Places"
            if validated_count
            else "Could not confirm any places",
        )
        if results:
            return dedup_validated_by_provider_id(
                results, self._extraction_config.confidence
            )
        return []
