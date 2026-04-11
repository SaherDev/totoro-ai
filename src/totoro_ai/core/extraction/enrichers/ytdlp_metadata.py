"""Level 2 — yt-dlp metadata caption enricher."""

import asyncio
import json
import sys

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

        data = await self._fetch_metadata(context.url)
        if data is None:
            return

        description: str | None = data.get("description")
        if description and context.caption is None:
            context.caption = description

        if context.title is None:
            context.title = data.get("title") or None
        if not context.hashtags:
            context.hashtags = data.get("tags") or []
        if context.platform is None:
            context.platform = data.get("extractor") or "unknown"
        if context.location_tag is None:
            context.location_tag = data.get("location") or None

    async def _fetch_metadata(self, url: str) -> dict | None:  # type: ignore[type-arg]
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-json",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp exited with code {proc.returncode} for {url}")

        return json.loads(stdout)  # type: ignore[no-any-return]
