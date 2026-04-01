"""Level 2.5 — Subtitle check enricher (stub, background phase).

Sets context.transcript so WhisperAudioEnricher can skip if subtitles found.
"""

import logging

from totoro_ai.core.extraction.models import ExtractionContext

logger = logging.getLogger(__name__)


class SubtitleCheckEnricher:
    """Check for subtitle tracks on the video.

    Background phase enricher. Runs before Whisper.
    Stub implementation — subtitle download not yet available.
    """

    async def enrich(self, context: ExtractionContext) -> None:
        if not context.url:
            return

        # TODO: Implement when yt-dlp subtitle extraction is available
        # Run yt-dlp --skip-download --write-subs --write-auto-subs {url}
        # If subtitle_text found:
        #   context.transcript = subtitle_text
        #   Run NER on subtitle_text, append CandidatePlace(source=SUBTITLE_CHECK)
        logger.debug("SubtitleCheckEnricher: stub, skipping")
