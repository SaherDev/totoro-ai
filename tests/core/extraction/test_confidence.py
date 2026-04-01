"""Unit tests for confidence scoring logic."""

import pytest

from totoro_ai.core.config import ConfidenceWeights
from totoro_ai.core.extraction.confidence import compute_confidence
from totoro_ai.core.extraction.models import ExtractionLevel
from totoro_ai.core.extraction.places_client import PlacesMatchQuality

_weights = ConfidenceWeights(
    base_scores={
        "EMOJI_REGEX": 0.95,
        "LLM_NER": 0.80,
        "SUBTITLE_CHECK": 0.75,
        "WHISPER_AUDIO": 0.65,
        "VISION_FRAMES": 0.55,
    },
    places_modifiers={
        "EXACT": 0.20,
        "FUZZY": 0.15,
        "CATEGORY_ONLY": 0.10,
        "NONE_CAP": 0.30,
    },
    multi_source_bonus=0.10,
    max_score=0.95,
)


class TestComputeConfidence:
    def test_emoji_regex_exact_match(self) -> None:
        score = compute_confidence(
            source=ExtractionLevel.EMOJI_REGEX,
            match_quality=PlacesMatchQuality.EXACT,
            weights=_weights,
        )
        # base=0.95 + modifier=0.20 = 1.15, capped at 0.95
        assert score == 0.95

    def test_llm_ner_exact_match(self) -> None:
        score = compute_confidence(
            source=ExtractionLevel.LLM_NER,
            match_quality=PlacesMatchQuality.EXACT,
            weights=_weights,
        )
        # base=0.80 + modifier=0.20 = 1.00, capped at 0.95
        assert score == 0.95

    def test_llm_ner_fuzzy_match(self) -> None:
        score = compute_confidence(
            source=ExtractionLevel.LLM_NER,
            match_quality=PlacesMatchQuality.FUZZY,
            weights=_weights,
        )
        # base=0.80 + modifier=0.15 = 0.95
        assert score == 0.95

    def test_llm_ner_category_only(self) -> None:
        score = compute_confidence(
            source=ExtractionLevel.LLM_NER,
            match_quality=PlacesMatchQuality.CATEGORY_ONLY,
            weights=_weights,
        )
        # base=0.80 + modifier=0.10 = 0.90
        assert score == 0.90

    def test_vision_frames_exact(self) -> None:
        score = compute_confidence(
            source=ExtractionLevel.VISION_FRAMES,
            match_quality=PlacesMatchQuality.EXACT,
            weights=_weights,
        )
        # base=0.55 + modifier=0.20 = 0.75
        assert score == 0.75

    def test_no_match_caps_at_none_cap(self) -> None:
        score = compute_confidence(
            source=ExtractionLevel.LLM_NER,
            match_quality=PlacesMatchQuality.NONE,
            weights=_weights,
        )
        # NONE: min(base=0.80, none_cap=0.30) = 0.30
        assert score == 0.30

    def test_corroboration_bonus(self) -> None:
        # Use VISION_FRAMES + CATEGORY_ONLY = 0.55 + 0.10 = 0.65, well below cap
        score_single = compute_confidence(
            source=ExtractionLevel.VISION_FRAMES,
            match_quality=PlacesMatchQuality.CATEGORY_ONLY,
            weights=_weights,
            corroborated=False,
        )
        score_corroborated = compute_confidence(
            source=ExtractionLevel.VISION_FRAMES,
            match_quality=PlacesMatchQuality.CATEGORY_ONLY,
            weights=_weights,
            corroborated=True,
        )
        assert score_corroborated - score_single == pytest.approx(0.10, abs=0.01)

    def test_max_cap(self) -> None:
        score = compute_confidence(
            source=ExtractionLevel.EMOJI_REGEX,
            match_quality=PlacesMatchQuality.EXACT,
            weights=_weights,
            corroborated=True,
        )
        assert score <= 0.95

    def test_all_scores_in_range(self) -> None:
        for level in ExtractionLevel:
            for quality in PlacesMatchQuality:
                for corroborated in [False, True]:
                    score = compute_confidence(
                        source=level,
                        match_quality=quality,
                        weights=_weights,
                        corroborated=corroborated,
                    )
                    assert 0.0 <= score <= 0.95, (
                        f"Score {score} out of range for "
                        f"{level}, {quality}, {corroborated}"
                    )
