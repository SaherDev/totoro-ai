"""ExtractionPipeline — three-phase runner for the extraction cascade."""

from __future__ import annotations

from typing import cast

from totoro_ai.core.config import ExtractionConfig
from totoro_ai.core.events.dispatcher import EventDispatcherProtocol
from totoro_ai.core.events.events import DomainEvent
from totoro_ai.core.extraction.enrichment_pipeline import EnrichmentPipeline
from totoro_ai.core.extraction.protocols import Enricher
from totoro_ai.core.extraction.types import (
    ExtractionContext,
    ExtractionLevel,
    ExtractionPending,
    ExtractionResult,
    ProvisionalResponse,
)
from totoro_ai.core.extraction.validator import PlacesValidatorProtocol


class ExtractionPipeline:
    """Three-phase extraction runner (ADR-008 — sequential async, not LangGraph).

    Phase 1: Inline enrichment (emoji regex, LLM NER, oEmbed, yt-dlp metadata)
             via EnrichmentPipeline, which also deduplicates candidates.
    Phase 2: Validate candidates against Google Places; return immediately on success.
    Phase 3: No inline candidates → dispatch ExtractionPending background event,
             return ProvisionalResponse.

    ExtractionPendingHandler is registered in the EventDispatcher at wiring time
    (Run 3) — in Run 2 the event is dispatched but silently dropped.
    """

    def __init__(
        self,
        enrichment: EnrichmentPipeline,
        validator: PlacesValidatorProtocol,
        background_enrichers: list[Enricher],
        event_dispatcher: EventDispatcherProtocol,
        extraction_config: ExtractionConfig,
    ) -> None:
        self._enrichment = enrichment
        self._validator = validator
        self._background_enrichers = background_enrichers
        self._event_dispatcher = event_dispatcher
        self._extraction_config = extraction_config

    async def run(
        self,
        url: str | None,
        user_id: str,
        supplementary_text: str = "",
    ) -> list[ExtractionResult] | ProvisionalResponse:
        context = ExtractionContext(
            url=url,
            user_id=user_id,
            supplementary_text=supplementary_text,
        )

        # Phase 1: inline enrichment + dedup
        await self._enrichment.run(context)

        # Phase 2: validate candidates
        results = await self._validator.validate(context.candidates)
        if results:
            return results

        # Phase 3: background dispatch
        pending_levels = [
            ExtractionLevel.SUBTITLE_CHECK,
            ExtractionLevel.WHISPER_AUDIO,
            ExtractionLevel.VISION_FRAMES,
        ]
        context.pending_levels = pending_levels
        await self._event_dispatcher.dispatch(
            cast(
                DomainEvent,
                ExtractionPending(
                    user_id=user_id,
                    url=url,
                    pending_levels=pending_levels,
                    context=context,
                ),
            )
        )
        return ProvisionalResponse(
            extraction_status="processing",
            confidence=0.0,
            message="We're still working on identifying this place.",
            pending_levels=pending_levels,
        )
