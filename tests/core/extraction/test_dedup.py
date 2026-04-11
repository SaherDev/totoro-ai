"""Tests for dedup_candidates and dedup_results_by_external_id."""

import pytest

from totoro_ai.core.config import ConfidenceConfig
from totoro_ai.core.extraction.dedup import (
    dedup_candidates,
    dedup_results_by_external_id,
)
from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
    ExtractionResult,
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


def test_same_name_different_case_merged() -> None:
    """RAMEN KAISUGI (emoji_regex) and ramen kaisugi (llm_ner) are the same place."""
    emoji = _candidate("RAMEN KAISUGI", source=ExtractionLevel.EMOJI_REGEX)
    ner = _candidate("ramen kaisugi", source=ExtractionLevel.LLM_NER)
    ctx = _ctx(emoji, ner)
    dedup_candidates(ctx)

    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].source == ExtractionLevel.EMOJI_REGEX
    assert ctx.candidates[0].corroborated is True


def test_same_name_with_punctuation_merged() -> None:
    """RAMEN KAISUGI! and RAMEN KAISUGI are the same place."""
    emoji = _candidate("RAMEN KAISUGI!", source=ExtractionLevel.EMOJI_REGEX)
    ner = _candidate("RAMEN KAISUGI", source=ExtractionLevel.LLM_NER)
    ctx = _ctx(emoji, ner)
    dedup_candidates(ctx)

    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].corroborated is True


def test_cross_enricher_dedup_emoji_wins_over_ner() -> None:
    """When emoji_regex and llm_ner both find the same place, emoji_regex wins."""
    emoji = _candidate("Bankara Ramen", source=ExtractionLevel.EMOJI_REGEX)
    ner = _candidate("Bankara Ramen", source=ExtractionLevel.LLM_NER)
    ctx = _ctx(ner, emoji)  # ner first in list
    dedup_candidates(ctx)

    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].source == ExtractionLevel.EMOJI_REGEX
    assert ctx.candidates[0].corroborated is True


# ---------------------------------------------------------------------------
# dedup_results_by_external_id — post-validation dedup
# ---------------------------------------------------------------------------


def _make_result(
    place_name: str = "Ramen Kaisugi",
    resolved_by: ExtractionLevel = ExtractionLevel.EMOJI_REGEX,
    external_id: str | None = "ChIJrUYs1Xuf4jARDnd40CFUUAE",
    confidence: float = 0.85,
    corroborated: bool = False,
) -> ExtractionResult:
    return ExtractionResult(
        place_name=place_name,
        address=None,
        city="Bangkok",
        cuisine=None,
        confidence=confidence,
        resolved_by=resolved_by,
        corroborated=corroborated,
        external_provider="google",
        external_id=external_id,
    )


def _config(
    corroboration_bonus: float = 0.10, max_score: float = 0.97
) -> ConfidenceConfig:
    return ConfidenceConfig(
        corroboration_bonus=corroboration_bonus, max_score=max_score
    )


def test_single_result_unchanged() -> None:
    result = _make_result()
    out = dedup_results_by_external_id([result], _config())
    assert out == [result]
    assert out[0].corroborated is False


def test_two_different_external_ids_both_kept() -> None:
    a = _make_result(external_id="id_a")
    b = _make_result(external_id="id_b")
    out = dedup_results_by_external_id([a, b], _config())
    assert len(out) == 2


def test_same_external_id_emoji_wins_over_ner() -> None:
    """emoji_regex beats llm_ner when both resolve to the same external_id."""
    emoji = _make_result(resolved_by=ExtractionLevel.EMOJI_REGEX, confidence=0.76)
    ner = _make_result(resolved_by=ExtractionLevel.LLM_NER, confidence=0.64)
    out = dedup_results_by_external_id([emoji, ner], _config())

    assert len(out) == 1
    assert out[0].resolved_by == ExtractionLevel.EMOJI_REGEX


def test_corroboration_bonus_applied_to_winner() -> None:
    """Winner gets corroboration_bonus added to confidence, capped at max_score."""
    emoji = _make_result(resolved_by=ExtractionLevel.EMOJI_REGEX, confidence=0.76)
    ner = _make_result(resolved_by=ExtractionLevel.LLM_NER, confidence=0.64)
    out = dedup_results_by_external_id(
        [emoji, ner], _config(corroboration_bonus=0.10, max_score=0.97)
    )

    assert out[0].confidence == pytest.approx(0.86)
    assert out[0].corroborated is True


def test_corroboration_bonus_capped_at_max_score() -> None:
    """Bonus does not push confidence above max_score."""
    emoji = _make_result(resolved_by=ExtractionLevel.EMOJI_REGEX, confidence=0.95)
    ner = _make_result(resolved_by=ExtractionLevel.LLM_NER, confidence=0.80)
    out = dedup_results_by_external_id(
        [emoji, ner], _config(corroboration_bonus=0.10, max_score=0.97)
    )

    assert out[0].confidence == pytest.approx(0.97)


def test_none_external_id_passes_through() -> None:
    """Results with external_id=None are never deduped."""
    a = _make_result(external_id=None)
    b = _make_result(external_id=None)
    out = dedup_results_by_external_id([a, b], _config())
    assert len(out) == 2


def test_mixed_none_and_real_external_ids() -> None:
    """None-id results pass through; real-id results are deduped separately."""
    no_id = _make_result(external_id=None)
    emoji = _make_result(resolved_by=ExtractionLevel.EMOJI_REGEX, external_id="same_id")
    ner = _make_result(resolved_by=ExtractionLevel.LLM_NER, external_id="same_id")
    out = dedup_results_by_external_id([no_id, emoji, ner], _config())

    assert len(out) == 2  # no_id + one winner
    statuses = {r.resolved_by for r in out}
    assert ExtractionLevel.LLM_NER not in statuses
    assert ExtractionLevel.EMOJI_REGEX in statuses


def test_empty_results_returns_empty() -> None:
    assert dedup_results_by_external_id([], _config()) == []
