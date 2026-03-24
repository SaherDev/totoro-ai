"""Unit tests for confidence scoring logic."""

import pytest

from totoro_ai.core.config import ConfidenceWeights
from totoro_ai.core.extraction.confidence import ExtractionSource, compute_confidence
from totoro_ai.core.extraction.places_client import PlacesMatchQuality

_weights = ConfidenceWeights(
    base_scores={"CAPTION": 0.70, "PLAIN_TEXT": 0.70, "SPEECH": 0.60, "OCR": 0.55},
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
    """Test suite for compute_confidence() function."""

    def test_exact_match_caption(self) -> None:
        """Test EXACT match with CAPTION source."""
        score = compute_confidence(
            source=ExtractionSource.CAPTION,
            match_quality=PlacesMatchQuality.EXACT,
            weights=_weights,
            corroborated=False,
        )
        # base=0.70 + modifier=0.20 = 0.90
        assert 0.85 <= score <= 0.95

    def test_exact_match_plain_text(self) -> None:
        """Test EXACT match with PLAIN_TEXT source."""
        score = compute_confidence(
            source=ExtractionSource.PLAIN_TEXT,
            match_quality=PlacesMatchQuality.EXACT,
            weights=_weights,
            corroborated=False,
        )
        # base=0.70 + modifier=0.20 = 0.90
        assert 0.85 <= score <= 0.95

    def test_fuzzy_match(self) -> None:
        """Test FUZZY match."""
        score = compute_confidence(
            source=ExtractionSource.CAPTION,
            match_quality=PlacesMatchQuality.FUZZY,
            weights=_weights,
            corroborated=False,
        )
        # base=0.70 + modifier=0.15 = 0.85
        assert 0.80 <= score <= 0.90

    def test_category_only_match(self) -> None:
        """Test CATEGORY_ONLY match."""
        score = compute_confidence(
            source=ExtractionSource.CAPTION,
            match_quality=PlacesMatchQuality.CATEGORY_ONLY,
            weights=_weights,
            corroborated=False,
        )
        # base=0.70 + modifier=0.10 = 0.80
        assert 0.75 <= score <= 0.85

    def test_no_match_caps_at_none_cap(self) -> None:
        """Test NONE match caps at NONE_CAP (0.30)."""
        score = compute_confidence(
            source=ExtractionSource.CAPTION,
            match_quality=PlacesMatchQuality.NONE,
            weights=_weights,
            corroborated=False,
        )
        # No Places match, capped at 0.30
        assert score <= 0.30

    def test_multi_source_bonus(self) -> None:
        """Test multi-source corroboration bonus."""
        score_single = compute_confidence(
            source=ExtractionSource.CAPTION,
            match_quality=PlacesMatchQuality.FUZZY,
            weights=_weights,
            corroborated=False,
        )
        score_corroborated = compute_confidence(
            source=ExtractionSource.CAPTION,
            match_quality=PlacesMatchQuality.FUZZY,
            weights=_weights,
            corroborated=True,
        )
        # Corroborated should be ~0.10 higher
        assert score_corroborated > score_single
        assert score_corroborated - score_single == pytest.approx(0.10, abs=0.01)

    def test_max_cap_at_0_95(self) -> None:
        """Test max cap at 0.95."""
        score = compute_confidence(
            source=ExtractionSource.CAPTION,
            match_quality=PlacesMatchQuality.EXACT,
            weights=_weights,
            corroborated=True,
        )
        assert score <= 0.95

    def test_score_range(self) -> None:
        """Test all scores fall within 0.0-0.95 range."""
        for source in ExtractionSource:
            for quality in PlacesMatchQuality:
                for corroborated in [False, True]:
                    score = compute_confidence(
                        source=source,
                        match_quality=quality,
                        weights=_weights,
                        corroborated=corroborated,
                    )
                    assert 0.0 <= score <= 0.95, (
                        f"Score {score} out of range for"
                        f" {source}, {quality}, {corroborated}"
                    )
