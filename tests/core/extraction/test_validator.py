"""Unit tests for GooglePlacesValidator."""

import pytest

from totoro_ai.core.config import ConfidenceWeights
from totoro_ai.core.extraction.models import CandidatePlace, ExtractionLevel
from totoro_ai.core.extraction.places_client import (
    PlacesMatchQuality,
    PlacesMatchResult,
)
from totoro_ai.core.extraction.validator import GooglePlacesValidator

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


class MockPlacesClient:
    def __init__(self, result: PlacesMatchResult) -> None:
        self._result = result
        self.call_count = 0

    async def validate_place(
        self, name: str, location: str | None = None
    ) -> PlacesMatchResult:
        self.call_count += 1
        return self._result


@pytest.mark.asyncio
class TestGooglePlacesValidator:
    async def test_empty_candidates_returns_none(self) -> None:
        client = MockPlacesClient(
            PlacesMatchResult(match_quality=PlacesMatchQuality.NONE)
        )
        validator = GooglePlacesValidator(client, _weights)  # type: ignore[arg-type]
        result = await validator.validate([])
        assert result is None

    async def test_single_candidate_exact_match(self) -> None:
        client = MockPlacesClient(
            PlacesMatchResult(
                match_quality=PlacesMatchQuality.EXACT,
                validated_name="Fuji Ramen Sukhumvit",
                external_provider="google",
                external_id="ChIJxyz",
                lat=13.7,
                lng=100.5,
            )
        )
        validator = GooglePlacesValidator(client, _weights)  # type: ignore[arg-type]
        candidates = [
            CandidatePlace(name="Fuji Ramen", source=ExtractionLevel.EMOJI_REGEX)
        ]
        results = await validator.validate(candidates)
        assert results is not None
        assert len(results) == 1
        assert results[0].place_name == "Fuji Ramen Sukhumvit"
        assert results[0].external_id == "ChIJxyz"
        assert results[0].resolved_by == ExtractionLevel.EMOJI_REGEX

    async def test_multiple_candidates_validated_in_parallel(self) -> None:
        client = MockPlacesClient(
            PlacesMatchResult(
                match_quality=PlacesMatchQuality.FUZZY,
                validated_name="Test Place",
                external_provider="google",
                external_id="abc",
            )
        )
        validator = GooglePlacesValidator(client, _weights)  # type: ignore[arg-type]
        candidates = [
            CandidatePlace(name=f"Place {i}", source=ExtractionLevel.LLM_NER)
            for i in range(5)
        ]
        results = await validator.validate(candidates)
        assert results is not None
        assert len(results) == 5
        assert client.call_count == 5

    async def test_corroboration_increases_confidence(self) -> None:
        client = MockPlacesClient(
            PlacesMatchResult(
                match_quality=PlacesMatchQuality.CATEGORY_ONLY,
                validated_name="Test",
                external_provider="google",
                external_id="x",
            )
        )
        validator = GooglePlacesValidator(client, _weights)  # type: ignore[arg-type]

        single = [CandidatePlace(name="A", source=ExtractionLevel.LLM_NER)]
        corroborated = [
            CandidatePlace(name="A", source=ExtractionLevel.LLM_NER, corroborated=True)
        ]

        r1 = await validator.validate(single)
        r2 = await validator.validate(corroborated)
        assert r1 is not None and r2 is not None
        assert r2[0].confidence > r1[0].confidence
