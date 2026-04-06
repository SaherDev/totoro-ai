"""Level 2 — yt-dlp metadata caption enricher."""

import asyncio
import json

from totoro_ai.core.extraction.types import ExtractionContext


class YtDlpMetadataEnricher:
    """Fetches video metadata via yt-dlp --dump-json.

    Caption enricher: populates context.caption (first-write-wins).
    Does NOT catch exceptions — they propagate to CircuitBreakerEnricher.
    Skips if context.url is None or context.caption is already set.
    """

    async def enrich(self, context: ExtractionContext) -> None:
        if not context.url:
            return
        if context.caption is not None:
            return  # first-write-wins

        description = await self._fetch_description(context.url)
        if description and context.caption is None:
            context.caption = description

    async def _fetch_description(self, url: str) -> str | None:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--dump-json",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp exited with code {proc.returncode} for {url}")

        data = json.loads(stdout)
        description: str | None = data.get("description")
        return description or None
