"""Tests for ExtractionService (ADR-054 / feature 019)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.api.schemas.extract_place import ExtractPlaceResponse
from totoro_ai.core.extraction.persistence import PlaceSaveOutcome
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.extraction.types import (
    ExtractionLevel,
    ProvisionalResponse,
    ValidatedCandidate,
)
from totoro_ai.core.places import (
    PlaceAttributes,
    PlaceCreate,
    PlaceObject,
    PlaceProvider,
    PlaceType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_place_create(
    place_name: str = "Fuji Ramen",
    external_id: str = "place_123",
) -> PlaceCreate:
    return PlaceCreate(
        user_id="user-1",
        place_name=place_name,
        place_type=PlaceType.food_and_drink,
        subcategory="restaurant",
        attributes=PlaceAttributes(cuisine="ramen"),
        provider=PlaceProvider.google,
        external_id=external_id,
    )


def _make_validated(
    place_name: str = "Fuji Ramen",
    external_id: str = "place_123",
    confidence: float = 0.87,
    resolved_by: ExtractionLevel = ExtractionLevel.LLM_NER,
) -> ValidatedCandidate:
    return ValidatedCandidate(
        place=_make_place_create(place_name=place_name, external_id=external_id),
        confidence=confidence,
        resolved_by=resolved_by,
        corroborated=False,
    )


def _make_place_object(
    place_id: str = "place-uuid-1",
    place_name: str = "Fuji Ramen",
) -> PlaceObject:
    return PlaceObject(
        place_id=place_id,
        place_name=place_name,
        place_type=PlaceType.food_and_drink,
        subcategory="restaurant",
        attributes=PlaceAttributes(cuisine="ramen"),
        provider_id="google:place_123",
    )


def _saved_outcome(
    validated: ValidatedCandidate | None = None, place_id: str = "place-uuid-1"
) -> PlaceSaveOutcome:
    vc = validated or _make_validated()
    return PlaceSaveOutcome(
        metadata=vc,
        place=_make_place_object(place_id=place_id, place_name=vc.place.place_name),
        place_id=place_id,
        status="saved",
    )


def _duplicate_outcome(
    validated: ValidatedCandidate | None = None, place_id: str = "existing-uuid"
) -> PlaceSaveOutcome:
    vc = validated or _make_validated()
    return PlaceSaveOutcome(
        metadata=vc,
        place=_make_place_object(place_id=place_id, place_name=vc.place.place_name),
        place_id=place_id,
        status="duplicate",
    )


def _below_threshold_outcome(
    validated: ValidatedCandidate | None = None,
) -> PlaceSaveOutcome:
    vc = validated or _make_validated(confidence=0.50)
    return PlaceSaveOutcome(
        metadata=vc,
        place=None,
        place_id=None,
        status="below_threshold",
    )


def _make_provisional(
    pending_levels: list[ExtractionLevel] | None = None,
) -> ProvisionalResponse:
    if pending_levels is None:
        pending_levels = [
            ExtractionLevel.SUBTITLE_CHECK,
            ExtractionLevel.WHISPER_AUDIO,
            ExtractionLevel.VISION_FRAMES,
        ]
    return ProvisionalResponse(
        extraction_status="processing",
        confidence=0.0,
        message="We're still working on identifying this place.",
        pending_levels=pending_levels,
    )


@pytest.fixture
def pipeline() -> MagicMock:
    p = MagicMock()
    p.run = AsyncMock(return_value=[_make_validated()])
    return p


@pytest.fixture
def persistence() -> MagicMock:
    ps = MagicMock()
    ps.save_and_emit = AsyncMock(return_value=[_saved_outcome()])
    return ps


@pytest.fixture
def service(pipeline: MagicMock, persistence: MagicMock) -> ExtractionService:
    return ExtractionService(pipeline=pipeline, persistence=persistence)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


async def test_empty_raw_input_raises_value_error(
    service: ExtractionService,
) -> None:
    with pytest.raises(ValueError, match="raw_input cannot be empty"):
        await service.run("", user_id="user-1")


async def test_whitespace_only_raw_input_raises_value_error(
    service: ExtractionService,
) -> None:
    with pytest.raises(ValueError, match="raw_input cannot be empty"):
        await service.run("   ", user_id="user-1")


# ---------------------------------------------------------------------------
# Saved path — new response shape
# ---------------------------------------------------------------------------


async def test_run_returns_extract_place_response(
    service: ExtractionService,
) -> None:
    response = await service.run("Fuji Ramen Bangkok", user_id="user-1")
    assert isinstance(response, ExtractPlaceResponse)


async def test_saved_item_has_place_confidence_and_status(
    service: ExtractionService,
) -> None:
    response = await service.run("Fuji Ramen Bangkok", user_id="user-1")
    assert len(response.results) == 1
    item = response.results[0]
    assert item.status == "saved"
    assert item.place is not None
    assert item.place.place_name == "Fuji Ramen"
    assert item.confidence == pytest.approx(0.87)


async def test_saved_path_item_count_matches_outcomes(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    vc_a = _make_validated("Place A", external_id="ext_a")
    vc_b = _make_validated("Place B", external_id="ext_b")
    pipeline.run = AsyncMock(return_value=[vc_a, vc_b])
    persistence.save_and_emit = AsyncMock(
        return_value=[
            _saved_outcome(vc_a, "uuid-a"),
            _saved_outcome(vc_b, "uuid-b"),
        ]
    )

    response = await service.run("some input", user_id="user-1")

    assert len(response.results) == 2
    assert {r.place.place_id for r in response.results if r.place} == {
        "uuid-a",
        "uuid-b",
    }
    assert all(r.status == "saved" for r in response.results)


async def test_saved_item_place_object_carries_tier1_fields(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    vc = _make_validated(place_name="Ichiran")
    pipeline.run = AsyncMock(return_value=[vc])
    persistence.save_and_emit = AsyncMock(
        return_value=[_saved_outcome(vc, "uuid-ichiran")]
    )

    response = await service.run("Ichiran Fukuoka", user_id="user-1")

    place = response.results[0].place
    assert place is not None
    assert isinstance(place, PlaceObject)
    assert place.place_name == "Ichiran"
    assert place.place_type == PlaceType.food_and_drink
    assert place.attributes.cuisine == "ramen"
    assert place.provider_id == "google:place_123"


# ---------------------------------------------------------------------------
# Duplicate path
# ---------------------------------------------------------------------------


async def test_duplicate_item_has_existing_place_and_status_duplicate(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    vc = _make_validated()
    pipeline.run = AsyncMock(return_value=[vc])
    persistence.save_and_emit = AsyncMock(
        return_value=[_duplicate_outcome(vc, "existing-uuid")]
    )

    response = await service.run("Fuji Ramen", user_id="user-1")

    assert len(response.results) == 1
    item = response.results[0]
    assert item.status == "duplicate"
    assert item.place is not None
    assert item.place.place_id == "existing-uuid"
    assert item.confidence == pytest.approx(0.87)


# ---------------------------------------------------------------------------
# Failed path — below_threshold collapses into "failed"
# ---------------------------------------------------------------------------


async def test_below_threshold_becomes_failed_item_with_confidence(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    vc = _make_validated(confidence=0.50)
    pipeline.run = AsyncMock(return_value=[vc])
    persistence.save_and_emit = AsyncMock(
        return_value=[_below_threshold_outcome(vc)]
    )

    response = await service.run("The Coffee Shop", user_id="user-1")

    assert len(response.results) == 1
    item = response.results[0]
    assert item.status == "failed"
    assert item.place is None
    assert item.confidence == pytest.approx(0.50)


async def test_no_candidates_returns_single_failed_item(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    """Pipeline returned nothing → single failed item with no place."""
    pipeline.run = AsyncMock(return_value=[])

    response = await service.run("nothing here", user_id="user-1")

    assert len(response.results) == 1
    item = response.results[0]
    assert item.status == "failed"
    assert item.place is None
    assert item.confidence is None
    persistence.save_and_emit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Pending path
# ---------------------------------------------------------------------------


async def test_provisional_response_returns_pending_item(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    pipeline.run = AsyncMock(return_value=_make_provisional())

    response = await service.run("https://tiktok.com/v/123", user_id="user-1")

    assert len(response.results) == 1
    item = response.results[0]
    assert item.status == "pending"
    assert item.place is None
    assert item.confidence is None
    persistence.save_and_emit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Pipeline delegation
# ---------------------------------------------------------------------------


async def test_pipeline_called_with_url_from_parsed_input(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    await service.run("https://tiktok.com/v/999 great ramen spot", user_id="user-1")
    call_kwargs = pipeline.run.call_args
    assert call_kwargs.kwargs["url"] == "https://tiktok.com/v/999"


async def test_pipeline_called_with_supplementary_text(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    await service.run("https://tiktok.com/v/999 great ramen spot", user_id="user-1")
    call_kwargs = pipeline.run.call_args
    assert call_kwargs.kwargs["supplementary_text"] == "great ramen spot"


async def test_pipeline_called_with_user_id(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    await service.run("Fuji Ramen", user_id="user-42")
    call_kwargs = pipeline.run.call_args
    assert call_kwargs.kwargs["user_id"] == "user-42"


async def test_pipeline_called_with_url_none_for_plain_text(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    await service.run("Fuji Ramen Bangkok no URL", user_id="user-1")
    call_kwargs = pipeline.run.call_args
    assert call_kwargs.kwargs["url"] is None


# ---------------------------------------------------------------------------
# source_url / request_id in response
# ---------------------------------------------------------------------------


async def test_source_url_set_to_parsed_url_on_saved_path(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    vc = _make_validated()
    pipeline.run = AsyncMock(return_value=[vc])
    persistence.save_and_emit = AsyncMock(return_value=[_saved_outcome(vc, "uuid-1")])

    response = await service.run(
        "https://tiktok.com/v/abc check this out", user_id="user-1"
    )

    assert response.source_url == "https://tiktok.com/v/abc"


async def test_source_url_none_for_plain_text_input(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    vc = _make_validated()
    pipeline.run = AsyncMock(return_value=[vc])
    persistence.save_and_emit = AsyncMock(return_value=[_saved_outcome(vc, "uuid-1")])

    response = await service.run("Fuji Ramen no url", user_id="user-1")

    assert response.source_url is None


async def test_source_url_set_on_pending_path(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    pipeline.run = AsyncMock(return_value=_make_provisional())

    response = await service.run("https://tiktok.com/v/xyz", user_id="user-1")

    assert response.source_url == "https://tiktok.com/v/xyz"


async def test_pending_response_carries_request_id(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    provisional = _make_provisional()
    provisional.request_id = "550e8400-e29b-41d4-a716-446655440000"
    pipeline.run = AsyncMock(return_value=provisional)

    response = await service.run("https://tiktok.com/v/123", user_id="user-1")

    assert response.request_id == "550e8400-e29b-41d4-a716-446655440000"


async def test_pending_response_empty_request_id_becomes_none(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    provisional = _make_provisional()
    provisional.request_id = ""
    pipeline.run = AsyncMock(return_value=provisional)

    response = await service.run("https://tiktok.com/v/123", user_id="user-1")

    assert response.request_id is None


async def test_saved_path_request_id_is_none(
    service: ExtractionService,
) -> None:
    response = await service.run("Fuji Ramen Bangkok", user_id="user-1")
    assert response.request_id is None


# ---------------------------------------------------------------------------
# Persistence delegation
# ---------------------------------------------------------------------------


async def test_persistence_called_with_pipeline_results(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    results = [_make_validated()]
    pipeline.run = AsyncMock(return_value=results)
    persistence.save_and_emit = AsyncMock(
        return_value=[_saved_outcome(results[0], "uuid-1")]
    )

    await service.run("Fuji Ramen", user_id="user-1")

    persistence.save_and_emit.assert_awaited_once_with(results, "user-1")
