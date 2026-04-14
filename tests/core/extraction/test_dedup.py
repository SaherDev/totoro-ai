"""Tests for dedup_candidates and dedup_validated_by_provider_id."""

import pytest

from totoro_ai.core.config import ConfidenceConfig
from totoro_ai.core.extraction.dedup import (
    dedup_candidates,
    dedup_validated_by_provider_id,
)
from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
    ValidatedCandidate,
)
from totoro_ai.core.places import (
    LocationContext,
    PlaceAttributes,
    PlaceCreate,
    PlaceProvider,
    PlaceType,
)


def _place(
    name: str = "Ramen Kaisugi",
    cuisine: str | None = None,
    price_hint: str | None = None,
    city: str | None = None,
    provider: PlaceProvider | None = None,
    external_id: str | None = None,
) -> PlaceCreate:
    return PlaceCreate(
        user_id="u1",
        place_name=name,
        place_type=PlaceType.food_and_drink,
        attributes=PlaceAttributes(
            cuisine=cuisine,
            price_hint=price_hint,
            location_context=LocationContext(city=city) if city else None,
        ),
        provider=provider,
        external_id=external_id,
    )


def _ctx(*candidates: CandidatePlace) -> ExtractionContext:
    ctx = ExtractionContext(url=None, user_id="u1")
    ctx.candidates = list(candidates)
    return ctx


def _candidate(
    name: str = "Ramen House",
    source: ExtractionLevel = ExtractionLevel.EMOJI_REGEX,
    corroborated: bool = False,
    cuisine: str | None = None,
    city: str | None = None,
) -> CandidatePlace:
    return CandidatePlace(
        place=_place(name=name, cuisine=cuisine, city=city),
        source=source,
        corroborated=corroborated,
    )


# ---------------------------------------------------------------------------
# dedup_candidates
# ---------------------------------------------------------------------------


def test_single_candidate_unchanged() -> None:
    c = _candidate("Ramen House")
    ctx = _ctx(c)
    dedup_candidates(ctx)
    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].place.place_name == "Ramen House"
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
    names = [c.place.place_name for c in ctx.candidates]
    assert "Ramen House" in names
    assert "Sushi Bar" in names
    ramen = next(c for c in ctx.candidates if c.place.place_name == "Ramen House")
    assert ramen.corroborated is True


def test_empty_candidates_noop() -> None:
    ctx = ExtractionContext(url=None, user_id="u1")
    ctx.candidates = []
    dedup_candidates(ctx)
    assert ctx.candidates == []


def test_same_name_different_case_merged() -> None:
    emoji = _candidate("RAMEN KAISUGI", source=ExtractionLevel.EMOJI_REGEX)
    ner = _candidate("ramen kaisugi", source=ExtractionLevel.LLM_NER)
    ctx = _ctx(emoji, ner)
    dedup_candidates(ctx)

    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].source == ExtractionLevel.EMOJI_REGEX
    assert ctx.candidates[0].corroborated is True


def test_same_name_with_punctuation_merged() -> None:
    emoji = _candidate("RAMEN KAISUGI!", source=ExtractionLevel.EMOJI_REGEX)
    ner = _candidate("RAMEN KAISUGI", source=ExtractionLevel.LLM_NER)
    ctx = _ctx(emoji, ner)
    dedup_candidates(ctx)

    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].corroborated is True


def test_dedup_candidates_inherits_attributes_from_loser() -> None:
    """Winner with no cuisine inherits from a loser that had one."""
    winner = _candidate(
        "Ramen House", source=ExtractionLevel.EMOJI_REGEX, cuisine=None
    )
    loser = _candidate(
        "Ramen House", source=ExtractionLevel.LLM_NER, cuisine="ramen"
    )
    ctx = _ctx(winner, loser)
    dedup_candidates(ctx)

    assert len(ctx.candidates) == 1
    winner_out = ctx.candidates[0]
    assert winner_out.source == ExtractionLevel.EMOJI_REGEX
    assert winner_out.place.attributes.cuisine == "ramen"


# ---------------------------------------------------------------------------
# dedup_validated_by_provider_id
# ---------------------------------------------------------------------------


def _make_validated(
    place_name: str = "Ramen Kaisugi",
    resolved_by: ExtractionLevel = ExtractionLevel.EMOJI_REGEX,
    external_id: str | None = "ChIJrUYs1Xuf4jARDnd40CFUUAE",
    confidence: float = 0.85,
    corroborated: bool = False,
    cuisine: str | None = None,
    city: str | None = "Bangkok",
) -> ValidatedCandidate:
    provider = PlaceProvider.google if external_id else None
    return ValidatedCandidate(
        place=_place(
            name=place_name,
            cuisine=cuisine,
            city=city,
            provider=provider,
            external_id=external_id,
        ),
        confidence=confidence,
        resolved_by=resolved_by,
        corroborated=corroborated,
    )


def _config(
    corroboration_bonus: float = 0.10, max_score: float = 0.97
) -> ConfidenceConfig:
    return ConfidenceConfig(
        corroboration_bonus=corroboration_bonus, max_score=max_score
    )


def test_single_result_unchanged() -> None:
    result = _make_validated()
    out = dedup_validated_by_provider_id([result], _config())
    assert out == [result]
    assert out[0].corroborated is False


def test_two_different_external_ids_both_kept() -> None:
    a = _make_validated(external_id="id_a")
    b = _make_validated(external_id="id_b")
    out = dedup_validated_by_provider_id([a, b], _config())
    assert len(out) == 2


def test_same_provider_id_emoji_wins_over_ner() -> None:
    emoji = _make_validated(
        resolved_by=ExtractionLevel.EMOJI_REGEX, confidence=0.76
    )
    ner = _make_validated(resolved_by=ExtractionLevel.LLM_NER, confidence=0.64)
    out = dedup_validated_by_provider_id([emoji, ner], _config())

    assert len(out) == 1
    assert out[0].resolved_by == ExtractionLevel.EMOJI_REGEX


def test_corroboration_bonus_applied_to_winner() -> None:
    emoji = _make_validated(
        resolved_by=ExtractionLevel.EMOJI_REGEX, confidence=0.76
    )
    ner = _make_validated(resolved_by=ExtractionLevel.LLM_NER, confidence=0.64)
    out = dedup_validated_by_provider_id(
        [emoji, ner], _config(corroboration_bonus=0.10, max_score=0.97)
    )

    assert out[0].confidence == pytest.approx(0.86)
    assert out[0].corroborated is True


def test_corroboration_bonus_capped_at_max_score() -> None:
    emoji = _make_validated(
        resolved_by=ExtractionLevel.EMOJI_REGEX, confidence=0.95
    )
    ner = _make_validated(resolved_by=ExtractionLevel.LLM_NER, confidence=0.80)
    out = dedup_validated_by_provider_id(
        [emoji, ner], _config(corroboration_bonus=0.10, max_score=0.97)
    )

    assert out[0].confidence == pytest.approx(0.97)


def test_none_external_id_passes_through() -> None:
    """Results with external_id=None are never deduped."""
    a = _make_validated(external_id=None)
    b = _make_validated(external_id=None)
    out = dedup_validated_by_provider_id([a, b], _config())
    assert len(out) == 2


def test_mixed_none_and_real_external_ids() -> None:
    no_id = _make_validated(external_id=None)
    emoji = _make_validated(
        resolved_by=ExtractionLevel.EMOJI_REGEX, external_id="same_id"
    )
    ner = _make_validated(
        resolved_by=ExtractionLevel.LLM_NER, external_id="same_id"
    )
    out = dedup_validated_by_provider_id([no_id, emoji, ner], _config())

    assert len(out) == 2  # no_id + one winner
    statuses = {r.resolved_by for r in out}
    assert ExtractionLevel.LLM_NER not in statuses
    assert ExtractionLevel.EMOJI_REGEX in statuses


def test_empty_results_returns_empty() -> None:
    assert dedup_validated_by_provider_id([], _config()) == []


def test_dedup_validated_inherits_attributes_from_loser() -> None:
    """Winner with no cuisine/city inherits from a loser — deep attribute merge."""
    emoji_winner = _make_validated(
        resolved_by=ExtractionLevel.EMOJI_REGEX,
        external_id="same_id",
        confidence=0.80,
        cuisine=None,
        city=None,
    )
    ner_loser = _make_validated(
        resolved_by=ExtractionLevel.LLM_NER,
        external_id="same_id",
        confidence=0.65,
        cuisine="ramen",
        city="Bangkok",
    )
    out = dedup_validated_by_provider_id([emoji_winner, ner_loser], _config())

    assert len(out) == 1
    winner = out[0]
    assert winner.resolved_by == ExtractionLevel.EMOJI_REGEX
    assert winner.place.attributes.cuisine == "ramen"
    assert winner.place.attributes.location_context is not None
    assert winner.place.attributes.location_context.city == "Bangkok"
