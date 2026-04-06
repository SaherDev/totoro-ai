"""Tests for TikTokOEmbedEnricher."""

from unittest.mock import AsyncMock, patch

import pytest

from totoro_ai.core.extraction.enrichers.tiktok_oembed import TikTokOEmbedEnricher
from totoro_ai.core.extraction.types import ExtractionContext


@pytest.fixture
def enricher() -> TikTokOEmbedEnricher:
    return TikTokOEmbedEnricher()


class TestTikTokOEmbedEnricher:
    async def test_sets_caption_from_oembed(
        self, enricher: TikTokOEmbedEnricher
    ) -> None:
        ctx = ExtractionContext(url="https://tiktok.com/v/123", user_id="u1")
        with patch.object(
            enricher, "_fetch_caption", new=AsyncMock(return_value="Fuji Ramen caption")
        ):
            await enricher.enrich(ctx)
        assert ctx.caption == "Fuji Ramen caption"

    async def test_first_write_wins_does_not_overwrite(
        self, enricher: TikTokOEmbedEnricher
    ) -> None:
        ctx = ExtractionContext(
            url="https://tiktok.com/v/123", user_id="u1", caption="existing"
        )
        with patch.object(
            enricher, "_fetch_caption", new=AsyncMock(return_value="new caption")
        ):
            await enricher.enrich(ctx)
        assert ctx.caption == "existing"

    async def test_skips_when_no_url(self, enricher: TikTokOEmbedEnricher) -> None:
        ctx = ExtractionContext(url=None, user_id="u1")
        with patch.object(enricher, "_fetch_caption", new=AsyncMock()) as mock_fetch:
            await enricher.enrich(ctx)
        mock_fetch.assert_not_called()

    async def test_propagates_http_error(self, enricher: TikTokOEmbedEnricher) -> None:
        """Exceptions must NOT be caught internally — circuit breaker handles them."""
        ctx = ExtractionContext(url="https://tiktok.com/v/123", user_id="u1")
        with (
            patch.object(
                enricher,
                "_fetch_caption",
                new=AsyncMock(side_effect=RuntimeError("timeout")),
            ),
            pytest.raises(RuntimeError, match="timeout"),
        ):
            await enricher.enrich(ctx)
