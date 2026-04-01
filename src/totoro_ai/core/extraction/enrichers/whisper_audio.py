"""Level 5 — Groq Whisper audio enricher (stub, background phase).

Two-tier: CDN URL direct to Groq, then in-memory pipe fallback.
Skips if context.transcript is already set by SubtitleCheckEnricher.
"""

import logging

from totoro_ai.core.extraction.models import ExtractionContext

logger = logging.getLogger(__name__)


class WhisperAudioEnricher:
    """Transcribe video audio via Groq Whisper and extract places.

    Background phase enricher. Skips if subtitles already resolved.
    Stub implementation — Whisper integration not yet available.
    """

    async def enrich(self, context: ExtractionContext) -> None:
        if context.transcript:
            return
        if not context.url:
            return

        # TODO: Implement Groq Whisper integration
        # Tier 1: CDN URL direct to Groq (zero bytes to Railway)
        # Tier 2: In-memory pipe (~240KB)
        # Hard timeout: 8 seconds
        # Run NER on transcript, append CandidatePlace(source=WHISPER_AUDIO)
        logger.debug("WhisperAudioEnricher: stub, skipping")
