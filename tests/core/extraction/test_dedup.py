"""Unit tests for candidate deduplication."""

from totoro_ai.core.extraction.dedup import dedup_candidates
from totoro_ai.core.extraction.models import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
)


def _make_context(candidates: list[CandidatePlace]) -> ExtractionContext:
    return ExtractionContext(url=None, user_id="u1", candidates=candidates)


class TestDedupCandidates:
    def test_empty_candidates(self) -> None:
        ctx = _make_context([])
        dedup_candidates(ctx)
        assert ctx.candidates == []

    def test_single_candidate_unchanged(self) -> None:
        c = CandidatePlace(name="Fuji Ramen", source=ExtractionLevel.LLM_NER)
        ctx = _make_context([c])
        dedup_candidates(ctx)
        assert len(ctx.candidates) == 1
        assert ctx.candidates[0].corroborated is False

    def test_same_name_different_sources_merged(self) -> None:
        c1 = CandidatePlace(name="Fuji Ramen", source=ExtractionLevel.EMOJI_REGEX)
        c2 = CandidatePlace(
            name="fuji ramen",
            city="Bangkok",
            cuisine="ramen",
            source=ExtractionLevel.LLM_NER,
        )
        ctx = _make_context([c1, c2])
        dedup_candidates(ctx)
        assert len(ctx.candidates) == 1
        merged = ctx.candidates[0]
        assert merged.corroborated is True
        # Kept EMOJI_REGEX (higher priority)
        assert merged.source == ExtractionLevel.EMOJI_REGEX
        # Filled missing fields from other candidate
        assert merged.city == "Bangkok"
        assert merged.cuisine == "ramen"

    def test_different_names_not_merged(self) -> None:
        c1 = CandidatePlace(name="Fuji Ramen", source=ExtractionLevel.EMOJI_REGEX)
        c2 = CandidatePlace(name="Sushi Dai", source=ExtractionLevel.LLM_NER)
        ctx = _make_context([c1, c2])
        dedup_candidates(ctx)
        assert len(ctx.candidates) == 2

    def test_three_sources_same_name(self) -> None:
        c1 = CandidatePlace(name="Fuji Ramen", source=ExtractionLevel.LLM_NER)
        c2 = CandidatePlace(name="Fuji Ramen", source=ExtractionLevel.EMOJI_REGEX)
        c3 = CandidatePlace(
            name="FUJI RAMEN",
            source=ExtractionLevel.SUBTITLE_CHECK,
            city="Tokyo",
        )
        ctx = _make_context([c1, c2, c3])
        dedup_candidates(ctx)
        assert len(ctx.candidates) == 1
        merged = ctx.candidates[0]
        assert merged.corroborated is True
        assert merged.source == ExtractionLevel.EMOJI_REGEX
        assert merged.city == "Tokyo"
