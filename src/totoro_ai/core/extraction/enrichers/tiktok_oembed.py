"""Level 1 — TikTok oEmbed caption enricher.

Populates context.caption via the public oEmbed API.
First-write-wins: only sets caption if still None.
"""

import logging

import httpx

from totoro_ai.core.config import get_config
from totoro_ai.core.extraction.models import ExtractionContext

logger = logging.getLogger(__name__)


class TikTokOEmbedEnricher:
    """Fetch TikTok video caption via oEmbed API.

    Caption enricher only — does not produce candidates.
    Skips if url is None or not a TikTok URL.
    """

    async def enrich(self, context: ExtractionContext) -> None:
        if not context.url or "tiktok.com" not in context.url:
            return

        config = get_config()
        tiktok_config = config.external_services.tiktok_oembed

        async with httpx.AsyncClient() as client:
            response = await client.get(
                tiktok_config.base_url,
                params={"url": context.url},
                timeout=tiktok_config.timeout_seconds,
            )
            response.raise_for_status()

        caption = response.json().get("title")
        if caption and context.caption is None:
            context.caption = caption
            logger.debug("TikTok oEmbed set caption: %s", caption[:80])
