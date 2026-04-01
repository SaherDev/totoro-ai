"""Integration tests for the three-phase ExtractionService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.api.schemas.extract_place import (
    ExtractPlaceResponse,
    ProvisionalResponse,
)
from totoro_ai.core.config import (
    ConfidenceWeights,
    ExtractionConfig,
    ExtractionThresholds,
)
from totoro_ai.core.extraction.models import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
)
from totoro_ai.core.extraction.places_client import (
    PlacesMatchQuality,
    PlacesMatchResult,
)
from totoro_ai.core.extraction.service import ExtractionService
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

_config = ExtractionConfig(
    confidence_weights=_weights,
    thresholds=ExtractionThresholds(store_silently=0.70, require_confirmation=0.30),
)


class FakeEnricher:
    """Enricher that adds fixed candidates to context."""

    def __init__(self, candidates: list[CandidatePlace]) -> None:
        self._candidates = candidates

    async def enrich(self, context: ExtractionContext) -> None:
        context.candidates.extend(self._candidates)


class EmptyEnricher:
    async def enrich(self, context: ExtractionContext) -> None:
        pass


def _mock_place_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_provider = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    return repo


def _mock_embedder() -> AsyncMock:
    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024])
    return embedder


def _mock_embedding_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.upsert_embedding = AsyncMock()
    return repo


def _mock_event_dispatcher() -> AsyncMock:
    return AsyncMock()


@pytest.mark.asyncio
class TestExtractionService:
    async def test_single_place_url_returns_one_result(self) -> None:
        candidates = [
            CandidatePlace(name="Fuji Ramen", source=ExtractionLevel.EMOJI_REGEX)
        ]
        enricher = FakeEnricher(candidates)

        mock_places_client = AsyncMock()
        mock_places_client.validate_place = AsyncMock(
            return_value=PlacesMatchResult(
                match_quality=PlacesMatchQuality.EXACT,
                validated_name="Fuji Ramen Bangkok",
                external_provider="google",
                external_id="ChIJxyz",
            )
        )

        validator = GooglePlacesValidator(mock_places_client, _weights)

        service = ExtractionService(
            enricher_chain=[enricher],  # type: ignore[list-item]
            validator=validator,
            place_repo=_mock_place_repo(),
            extraction_config=_config,
            embedder=_mock_embedder(),
            embedding_repo=_mock_embedding_repo(),
            event_dispatcher=_mock_event_dispatcher(),
        )

        result = await service.run("📍Fuji Ramen", "user-1")
        assert isinstance(result, ExtractPlaceResponse)
        assert len(result.places) == 1
        assert result.places[0].place_name == "Fuji Ramen Bangkok"

    async def test_multi_place_returns_multiple_results(self) -> None:
        candidates = [
            CandidatePlace(name="Place A", source=ExtractionLevel.EMOJI_REGEX),
            CandidatePlace(name="Place B", source=ExtractionLevel.LLM_NER),
            CandidatePlace(name="Place C", source=ExtractionLevel.LLM_NER),
        ]
        enricher = FakeEnricher(candidates)

        mock_places_client = AsyncMock()
        mock_places_client.validate_place = AsyncMock(
            return_value=PlacesMatchResult(
                match_quality=PlacesMatchQuality.EXACT,
                validated_name="Validated",
                external_provider="google",
                external_id="id123",
            )
        )

        validator = GooglePlacesValidator(mock_places_client, _weights)

        service = ExtractionService(
            enricher_chain=[enricher],  # type: ignore[list-item]
            validator=validator,
            place_repo=_mock_place_repo(),
            extraction_config=_config,
            embedder=_mock_embedder(),
            embedding_repo=_mock_embedding_repo(),
            event_dispatcher=_mock_event_dispatcher(),
        )

        result = await service.run("top 5 ramen", "user-1")
        assert isinstance(result, ExtractPlaceResponse)
        assert len(result.places) == 3

    async def test_no_candidates_returns_provisional(self) -> None:
        service = ExtractionService(
            enricher_chain=[EmptyEnricher()],  # type: ignore[list-item]
            validator=GooglePlacesValidator(AsyncMock(), _weights),
            place_repo=_mock_place_repo(),
            extraction_config=_config,
            embedder=_mock_embedder(),
            embedding_repo=_mock_embedding_repo(),
            event_dispatcher=_mock_event_dispatcher(),
        )

        result = await service.run("some vague text", "user-1")
        assert isinstance(result, ProvisionalResponse)
        assert result.status == "pending"

    async def test_empty_input_raises(self) -> None:
        service = ExtractionService(
            enricher_chain=[EmptyEnricher()],  # type: ignore[list-item]
            validator=GooglePlacesValidator(AsyncMock(), _weights),
            place_repo=_mock_place_repo(),
            extraction_config=_config,
            embedder=_mock_embedder(),
            embedding_repo=_mock_embedding_repo(),
            event_dispatcher=_mock_event_dispatcher(),
        )

        with pytest.raises(ValueError, match="raw_input cannot be empty"):
            await service.run("", "user-1")

    async def test_duplicate_place_skipped(self) -> None:
        candidates = [CandidatePlace(name="Fuji Ramen", source=ExtractionLevel.LLM_NER)]
        enricher = FakeEnricher(candidates)

        mock_places_client = AsyncMock()
        mock_places_client.validate_place = AsyncMock(
            return_value=PlacesMatchResult(
                match_quality=PlacesMatchQuality.EXACT,
                validated_name="Fuji Ramen",
                external_provider="google",
                external_id="existing-id",
            )
        )

        # Existing place found — dedup should return existing ID
        existing_place = MagicMock()
        existing_place.id = "existing-place-uuid"
        place_repo = _mock_place_repo()
        place_repo.get_by_provider = AsyncMock(return_value=existing_place)

        validator = GooglePlacesValidator(mock_places_client, _weights)

        service = ExtractionService(
            enricher_chain=[enricher],  # type: ignore[list-item]
            validator=validator,
            place_repo=place_repo,
            extraction_config=_config,
            embedder=_mock_embedder(),
            embedding_repo=_mock_embedding_repo(),
            event_dispatcher=_mock_event_dispatcher(),
        )

        result = await service.run("Fuji Ramen", "user-1")
        assert isinstance(result, ExtractPlaceResponse)
        assert result.places[0].place_id == "existing-place-uuid"
        # save() should NOT have been called since place already exists
        place_repo.save.assert_not_called()

    async def test_url_input_dispatches_background_on_no_results(self) -> None:
        service = ExtractionService(
            enricher_chain=[EmptyEnricher()],  # type: ignore[list-item]
            validator=GooglePlacesValidator(AsyncMock(), _weights),
            place_repo=_mock_place_repo(),
            extraction_config=_config,
            embedder=_mock_embedder(),
            embedding_repo=_mock_embedding_repo(),
            event_dispatcher=_mock_event_dispatcher(),
        )

        result = await service.run("https://tiktok.com/v/123", "user-1")
        assert isinstance(result, ProvisionalResponse)
        assert len(result.pending_levels) > 0

    async def test_plain_text_no_background_dispatch(self) -> None:
        service = ExtractionService(
            enricher_chain=[EmptyEnricher()],  # type: ignore[list-item]
            validator=GooglePlacesValidator(AsyncMock(), _weights),
            place_repo=_mock_place_repo(),
            extraction_config=_config,
            embedder=_mock_embedder(),
            embedding_repo=_mock_embedding_repo(),
            event_dispatcher=_mock_event_dispatcher(),
        )

        result = await service.run("some place text", "user-1")
        assert isinstance(result, ProvisionalResponse)
        assert result.pending_levels == []
