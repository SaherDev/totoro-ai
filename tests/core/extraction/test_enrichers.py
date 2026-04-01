"""Unit tests for enricher implementations."""

import pytest

from totoro_ai.core.extraction.enrichers.emoji_regex import EmojiRegexEnricher
from totoro_ai.core.extraction.enrichers.parallel_group import ParallelEnricherGroup
from totoro_ai.core.extraction.models import (
    ExtractionContext,
    ExtractionLevel,
)


def _make_context(**kwargs: object) -> ExtractionContext:
    defaults: dict[str, object] = {"url": None, "user_id": "u1"}
    defaults.update(kwargs)
    return ExtractionContext(**defaults)  # type: ignore[arg-type]


class TestEmojiRegexEnricher:
    @pytest.mark.asyncio
    async def test_finds_pin_emoji_places(self) -> None:
        ctx = _make_context(
            caption="Check out these spots! 📍Fuji Ramen 📍Sushi Dai 📍Tonkatsu Maisen"
        )
        enricher = EmojiRegexEnricher()
        await enricher.enrich(ctx)
        names = [c.name for c in ctx.candidates]
        assert "Fuji Ramen" in names
        assert "Sushi Dai" in names
        assert "Tonkatsu Maisen" in names
        assert all(c.source == ExtractionLevel.EMOJI_REGEX for c in ctx.candidates)

    @pytest.mark.asyncio
    async def test_finds_at_mention_places(self) -> None:
        ctx = _make_context(caption="Dinner at @Fuji Ramen was amazing")
        enricher = EmojiRegexEnricher()
        await enricher.enrich(ctx)
        names = [c.name for c in ctx.candidates]
        assert "Fuji Ramen" in names

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty(self) -> None:
        ctx = _make_context(caption="no places here at all")
        enricher = EmojiRegexEnricher()
        await enricher.enrich(ctx)
        assert ctx.candidates == []

    @pytest.mark.asyncio
    async def test_falls_back_to_supplementary_text(self) -> None:
        ctx = _make_context(supplementary_text="📍Tokyo Tower is great")
        enricher = EmojiRegexEnricher()
        await enricher.enrich(ctx)
        names = [c.name for c in ctx.candidates]
        assert "Tokyo Tower" in names

    @pytest.mark.asyncio
    async def test_deduplicates_within_same_text(self) -> None:
        ctx = _make_context(caption="📍Fuji Ramen 📍Fuji Ramen")
        enricher = EmojiRegexEnricher()
        await enricher.enrich(ctx)
        # Regex deduplicates within its own output
        assert len(ctx.candidates) == 1

    @pytest.mark.asyncio
    async def test_skips_if_no_text(self) -> None:
        ctx = _make_context()
        enricher = EmojiRegexEnricher()
        await enricher.enrich(ctx)
        assert ctx.candidates == []


class _TrackingEnricher:
    def __init__(self, name: str) -> None:
        self.name = name
        self.called = False

    async def enrich(self, context: ExtractionContext) -> None:
        self.called = True


class _FailingEnricher:
    async def enrich(self, context: ExtractionContext) -> None:
        raise RuntimeError("boom")


class TestParallelEnricherGroup:
    @pytest.mark.asyncio
    async def test_runs_all_enrichers(self) -> None:
        e1 = _TrackingEnricher("a")
        e2 = _TrackingEnricher("b")
        group = ParallelEnricherGroup([e1, e2])  # type: ignore[list-item]
        ctx = _make_context()
        await group.enrich(ctx)
        assert e1.called
        assert e2.called

    @pytest.mark.asyncio
    async def test_failure_does_not_block_others(self) -> None:
        e1 = _FailingEnricher()
        e2 = _TrackingEnricher("b")
        group = ParallelEnricherGroup([e1, e2])  # type: ignore[list-item]
        ctx = _make_context()
        await group.enrich(ctx)
        assert e2.called
