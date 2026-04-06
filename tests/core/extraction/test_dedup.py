"""Tests for dedup_candidates (Phase 6 — extraction cascade Run 2)."""


from totoro_ai.core.extraction.dedup import dedup_candidates
from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
)


def _ctx(*candidates: CandidatePlace) -> ExtractionContext:
    ctx = ExtractionContext(url=None, user_id="u1")
    ctx.candidates = list(candidates)
    return ctx


def _candidate(
    name: str,
    source: ExtractionLevel = ExtractionLevel.EMOJI_REGEX,
    corroborated: bool = False,
) -> CandidatePlace:
    return CandidatePlace(
        name=name,
        city=None,
        cuisine=None,
        source=source,
        corroborated=corroborated,
    )


def test_single_candidate_unchanged() -> None:
    c = _candidate("Ramen House")
    ctx = _ctx(c)
    dedup_candidates(ctx)
    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].name == "Ramen House"
    assert ctx.candidates[0].corroborated is False


def test_two_different_names_both_kept() -> None:
    ctx = _ctx(_candidate("Ramen House"), _candidate("Sushi Bar"))
    dedup_candidates(ctx)
    assert len(ctx.candidates) == 2


def test_same_name_different_levels_lower_index_wins() -> None:
    emoji = _candidate("Ramen House", source=ExtractionLevel.EMOJI_REGEX)
    ner = _candidate("Ramen House", source=ExtractionLevel.LLM_NER)
    ctx = _ctx(emoji, ner)
    dedup_candidates(ctx)

    assert len(ctx.candidates) == 1
    winner = ctx.candidates[0]
    assert winner.source == ExtractionLevel.EMOJI_REGEX
    assert winner.corroborated is True


def test_three_candidates_two_same_one_different() -> None:
    regex = _candidate("Ramen House", source=ExtractionLevel.EMOJI_REGEX)
    ner = _candidate("Ramen House", source=ExtractionLevel.LLM_NER)
    other = _candidate("Sushi Bar", source=ExtractionLevel.LLM_NER)
    ctx = _ctx(regex, ner, other)
    dedup_candidates(ctx)

    assert len(ctx.candidates) == 2
    names = [c.name for c in ctx.candidates]
    assert "Ramen House" in names
    assert "Sushi Bar" in names
    ramen = next(c for c in ctx.candidates if c.name == "Ramen House")
    assert ramen.corroborated is True


def test_same_name_same_level_keeps_first_marks_corroborated() -> None:
    first = _candidate("Pizza Roma", source=ExtractionLevel.LLM_NER)
    second = _candidate("Pizza Roma", source=ExtractionLevel.LLM_NER)
    ctx = _ctx(first, second)
    dedup_candidates(ctx)

    assert len(ctx.candidates) == 1
    assert ctx.candidates[0] is first
    assert ctx.candidates[0].corroborated is True


def test_empty_candidates_noop() -> None:
    ctx = ExtractionContext(url=None, user_id="u1")
    ctx.candidates = []
    dedup_candidates(ctx)
    assert ctx.candidates == []
