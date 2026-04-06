"""Tests for EmojiRegexEnricher."""

import pytest

from totoro_ai.core.extraction.enrichers.emoji_regex import EmojiRegexEnricher
from totoro_ai.core.extraction.types import CandidatePlace, ExtractionContext, ExtractionLevel


@pytest.fixture
def enricher() -> EmojiRegexEnricher:
    return EmojiRegexEnricher()


class TestEmojiRegexEnricher:
    async def test_finds_single_emoji_marker(self, enricher: EmojiRegexEnricher) -> None:
        ctx = ExtractionContext(url=None, user_id="u1", caption="Best ramen 📍Fuji Ramen")
        await enricher.enrich(ctx)
        assert len(ctx.candidates) == 1
        assert ctx.candidates[0].name == "Fuji Ramen"
        assert ctx.candidates[0].source == ExtractionLevel.EMOJI_REGEX

    async def test_finds_multiple_emoji_markers(self, enricher: EmojiRegexEnricher) -> None:
        ctx = ExtractionContext(
            url=None,
            user_id="u1",
            caption="📍Place One 📍Place Two 📍Place Three",
        )
        await enricher.enrich(ctx)
        emoji_candidates = [c for c in ctx.candidates if c.name in ("Place One", "Place Two", "Place Three")]
        assert len(emoji_candidates) == 3

    async def test_finds_at_mention(self, enricher: EmojiRegexEnricher) -> None:
        ctx = ExtractionContext(url=None, user_id="u1", caption="Great food @FujiRamen today")
        await enricher.enrich(ctx)
        at_candidates = [c for c in ctx.candidates if c.name == "FujiRamen"]
        assert len(at_candidates) == 1

    async def test_uses_supplementary_text_when_no_caption(self, enricher: EmojiRegexEnricher) -> None:
        ctx = ExtractionContext(url=None, user_id="u1", supplementary_text="📍Fuji Ramen")
        await enricher.enrich(ctx)
        assert len(ctx.candidates) == 1

    async def test_skips_when_no_text(self, enricher: EmojiRegexEnricher) -> None:
        ctx = ExtractionContext(url=None, user_id="u1")
        await enricher.enrich(ctx)
        assert ctx.candidates == []

    async def test_does_not_skip_when_candidates_exist(self, enricher: EmojiRegexEnricher) -> None:
        """No skip guard — appends even when candidates already present."""
        ctx = ExtractionContext(url=None, user_id="u1", caption="📍New Place")
        ctx.candidates.append(
            CandidatePlace(name="Existing", city=None, cuisine=None, source=ExtractionLevel.LLM_NER)
        )
        await enricher.enrich(ctx)
        assert len(ctx.candidates) == 2

    async def test_extracts_city_from_hashtag(self, enricher: EmojiRegexEnricher) -> None:
        ctx = ExtractionContext(
            url=None, user_id="u1", caption="📍Fuji Ramen #bangkok best spot"
        )
        await enricher.enrich(ctx)
        assert len(ctx.candidates) >= 1
        assert ctx.candidates[0].city == "bangkok"

    async def test_returns_none(self, enricher: EmojiRegexEnricher) -> None:
        ctx = ExtractionContext(url=None, user_id="u1")
        result = await enricher.enrich(ctx)
        assert result is None
