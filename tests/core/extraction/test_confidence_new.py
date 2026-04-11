"""Tests for calculate_confidence() — multiplicative formula.

Caps at config.max_score (default 0.97) instead of 1.0.
"""

import pytest

from totoro_ai.core.config import ConfidenceConfig
from totoro_ai.core.extraction.confidence import calculate_confidence
from totoro_ai.core.extraction.types import ExtractionLevel

_config = ConfidenceConfig(
    base_scores={
        "emoji_regex": 0.95,
        "llm_ner": 0.80,
        "subtitle_check": 0.75,
        "whisper_audio": 0.65,
        "vision_frames": 0.55,
    },
    corroboration_bonus=0.10,
    max_score=0.97,
)


class TestCalculateConfidence:
    def test_emoji_regex_exact_match(self) -> None:
        # 0.95 * 1.0 + 0.0 = 0.95
        score = calculate_confidence(ExtractionLevel.EMOJI_REGEX, 1.0, False, _config)
        assert score == pytest.approx(0.95)

    def test_emoji_regex_corroborated_capped(self) -> None:
        # min(0.95 * 1.0 + 0.10, 0.97) = 0.97 (1.05 exceeds max_score)
        score = calculate_confidence(ExtractionLevel.EMOJI_REGEX, 1.0, True, _config)
        assert score == pytest.approx(0.97)

    def test_llm_ner_ambiguous_match(self) -> None:
        # 0.80 * 0.6 + 0.0 = 0.48
        score = calculate_confidence(ExtractionLevel.LLM_NER, 0.6, False, _config)
        assert score == pytest.approx(0.48)

    def test_vision_frames_no_match(self) -> None:
        # 0.55 * 0.3 + 0.0 = 0.165
        score = calculate_confidence(ExtractionLevel.VISION_FRAMES, 0.3, False, _config)
        assert score == pytest.approx(0.165)

    def test_whisper_audio_with_corroboration(self) -> None:
        # min(0.65 * 0.8 + 0.10, 0.97) = min(0.62, 0.97) = 0.62
        score = calculate_confidence(ExtractionLevel.WHISPER_AUDIO, 0.8, True, _config)
        assert score == pytest.approx(0.62)

    def test_subtitle_check_exact(self) -> None:
        # 0.75 * 1.0 + 0.0 = 0.75
        score = calculate_confidence(
            ExtractionLevel.SUBTITLE_CHECK, 1.0, False, _config
        )
        assert score == pytest.approx(0.75)

    def test_cap_at_max_score(self) -> None:
        # Even if formula exceeds max_score, result is capped at max_score
        config = ConfidenceConfig(
            base_scores={"emoji_regex": 0.95}, corroboration_bonus=0.20, max_score=0.97
        )
        score = calculate_confidence(ExtractionLevel.EMOJI_REGEX, 1.0, True, config)
        assert score == pytest.approx(0.97)
        assert score <= 0.97

    def test_unknown_level_defaults_to_0_50(self) -> None:
        # A config missing a key falls back to 0.50 base
        sparse_config = ConfidenceConfig(
            base_scores={}, corroboration_bonus=0.10, max_score=0.97
        )
        score = calculate_confidence(
            ExtractionLevel.EMOJI_REGEX, 1.0, False, sparse_config
        )
        assert score == pytest.approx(0.50)

    @pytest.mark.parametrize("level", list(ExtractionLevel))
    def test_all_levels_return_valid_range(self, level: ExtractionLevel) -> None:
        score = calculate_confidence(level, 1.0, False, _config)
        assert 0.0 <= score <= _config.max_score
