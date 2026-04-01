"""Level 2 — yt-dlp metadata caption enricher (stub).

Populates context.caption via yt-dlp --dump-json.
First-write-wins: only sets caption if still None.
"""

import logging

from totoro_ai.core.extraction.models import ExtractionContext

logger = logging.getLogger(__name__)


class YtDlpMetadataEnricher:
    """Fetch video caption via yt-dlp metadata dump.

    Stub implementation — yt-dlp binary not yet available in this environment.
    Caption enricher only — does not produce candidates.
    Skips if url is None.
    """

    async def enrich(self, context: ExtractionContext) -> None:
        if not context.url:
            return

        # TODO: Implement when yt-dlp is available
        # Run yt-dlp --dump-json {url}, extract description field
        # if parsed_caption and context.caption is None:
        #     context.caption = parsed_caption
        logger.debug("YtDlpMetadataEnricher: stub, skipping")
