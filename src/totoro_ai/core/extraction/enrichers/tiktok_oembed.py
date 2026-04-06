"""Level 1 — TikTok oEmbed caption enricher."""

import httpx

from totoro_ai.core.extraction.types import ExtractionContext

_TIKTOK_OEMBED_URL = "https://www.tiktok.com/oembed"
_TIMEOUT_SECONDS = 10.0  # TODO: move to config if oEmbed URL needs per-env override


class TikTokOEmbedEnricher:
    """Fetches TikTok video caption via oEmbed API.

    Caption enricher: populates context.caption (first-write-wins).
    Does NOT catch exceptions — they propagate to CircuitBreakerEnricher.
    Skips if context.url is None or context.caption is already set.
    """

    async def enrich(self, context: ExtractionContext) -> None:
        if not context.url:
            return
        if context.caption is not None:
            return  # first-write-wins

        caption = await self._fetch_caption(context.url)
        if caption and context.caption is None:
            context.caption = caption

    async def _fetch_caption(self, url: str) -> str | None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                _TIKTOK_OEMBED_URL,
                params={"url": url},
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()

        data = response.json()
        return data.get("title") or None
