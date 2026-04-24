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


class TooManyCandidatesError(Exception):
    """Raised when Phase 1 enrichment produces more candidates than allowed.

    The pipeline refuses to validate or persist anything in this case —
    the whole request is dropped. The service catches this exception and
    returns a `failed` envelope with a user-facing reason in the SSE stream.
    """

    def __init__(self, found: int, limit: int) -> None:
        super().__init__(f"Found {found} candidates; limit is {limit}")
        self.found = found
        self.limit = limit


def _enforce_candidate_limit(
    context: ExtractionContext, limit: int, emit: EmitFn
) -> None:
    """Drop the entire request when too many candidates were found.

    Runs after Phase 1 enrichment + dedup, before validation. Emits a
    `save.cap_exceeded` reasoning step with counts and raises
    `TooManyCandidatesError` so the service can return a `failed`
    envelope without spending Google Places quota or DB writes.
    """
    found = len(context.candidates)
    if found <= limit:
        return
    emit(
        "save.cap_exceeded",
        f"Found {found} possible places, more than the limit of {limit} — "
        "skipping this request to protect the system",
    )
    raise TooManyCandidatesError(found=found, limit=limit)


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
        limit: int | None = None,
    ) -> list[ValidatedCandidate]:
        """Run the extraction cascade.

        `limit`, when supplied, overrides `extraction.max_candidates` for
        this single request — the agent (or any other caller) can tighten
        the cap below the config default. `None` falls back to the config.
        """
        _emit: EmitFn = emit or (lambda step, summary, duration_ms=None: None)
        effective_limit = (
            limit if limit is not None else self._extraction_config.max_candidates
        )

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
        _enforce_candidate_limit(context, effective_limit, _emit)

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
        # Phase 3 starts from the Phase 1-capped set, but subtitle, whisper,
        # and vision enrichers each add their own candidates. Re-enforce
        # the cap before the second validation pass for the same reason —
        # protect Google quota + DB writes from a noisy deep pass.
        _enforce_candidate_limit(context, effective_limit, _emit)

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
