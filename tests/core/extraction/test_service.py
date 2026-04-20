"""Tests for ExtractionService (ADR-054 / feature 019)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.api.schemas.extract_place import ExtractPlaceResponse
from totoro_ai.core.extraction.persistence import PlaceSaveOutcome
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.extraction.types import (
    ExtractionLevel,
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


def _below_threshold_outcome(
    validated: ValidatedCandidate | None = None,
) -> PlaceSaveOutcome:
    vc = validated or _make_validated(confidence=0.20)
    return PlaceSaveOutcome(metadata=vc, place=None, place_id=None, status="below_threshold")


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
def status_repo() -> MagicMock:
    sr = MagicMock()
    sr.write = AsyncMock()
    return sr


@pytest.fixture
def service(
    pipeline: MagicMock,
    persistence: MagicMock,
    status_repo: MagicMock,
) -> ExtractionService:
    return ExtractionService(
        pipeline=pipeline, persistence=persistence, status_repo=status_repo
    )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


async def test_empty_raw_input_raises_value_error(service: ExtractionService) -> None:
    with pytest.raises(ValueError, match="raw_input cannot be empty"):
        await service.run("", user_id="user-1")


async def test_whitespace_only_raw_input_raises_value_error(
    service: ExtractionService,
) -> None:
    with pytest.raises(ValueError, match="raw_input cannot be empty"):
        await service.run("   ", user_id="user-1")


# ---------------------------------------------------------------------------
# Immediate response — always pending
# ---------------------------------------------------------------------------


async def test_run_returns_extract_place_response(service: ExtractionService) -> None:
    response = await service.run("Fuji Ramen Bangkok", user_id="user-1")
    assert isinstance(response, ExtractPlaceResponse)


async def test_run_always_returns_pending_status(service: ExtractionService) -> None:
    for raw_input in ("Fuji Ramen Bangkok", "https://tiktok.com/v/123"):
        response = await service.run(raw_input, user_id="user-1")
        assert response.results[0].status == "pending"
        assert response.results[0].place is None
        assert response.results[0].confidence is None


async def test_url_input_sets_source_url(service: ExtractionService) -> None:
    response = await service.run(
        "https://tiktok.com/v/abc great ramen", user_id="user-1"
    )
    assert response.source_url == "https://tiktok.com/v/abc"


async def test_plain_text_source_url_is_none(service: ExtractionService) -> None:
    response = await service.run("Fuji Ramen Bangkok", user_id="user-1")
    assert response.source_url is None


async def test_response_carries_request_id(service: ExtractionService) -> None:
    response = await service.run("Fuji Ramen Bangkok", user_id="user-1")
    assert response.request_id is not None
    assert len(response.request_id) == 32


# ---------------------------------------------------------------------------
# Background task — pipeline + persistence + status write
# ---------------------------------------------------------------------------


async def test_background_task_calls_pipeline_with_correct_args(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    await service.run("https://tiktok.com/v/999 great ramen", user_id="user-42")
    await asyncio.sleep(0)

    pipeline.run.assert_awaited_once()
    kw = pipeline.run.call_args.kwargs
    assert kw["url"] == "https://tiktok.com/v/999"
    assert kw["supplementary_text"] == "great ramen"
    assert kw["user_id"] == "user-42"


async def test_background_task_calls_pipeline_url_none_for_plain_text(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    await service.run("Fuji Ramen no url", user_id="user-1")
    await asyncio.sleep(0)

    kw = pipeline.run.call_args.kwargs
    assert kw["url"] is None


async def test_background_task_saves_and_writes_status(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
    status_repo: MagicMock,
) -> None:
    results = [_make_validated()]
    pipeline.run = AsyncMock(return_value=results)
    persistence.save_and_emit = AsyncMock(return_value=[_saved_outcome(results[0])])

    response = await service.run("Fuji Ramen", user_id="user-1")
    await asyncio.sleep(0)

    persistence.save_and_emit.assert_awaited_once()
    status_repo.write.assert_awaited_once()
    assert status_repo.write.call_args.args[0] == response.request_id


async def test_background_task_no_results_writes_failed_status(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
    status_repo: MagicMock,
) -> None:
    pipeline.run = AsyncMock(return_value=[])

    await service.run("https://tiktok.com/v/abc", user_id="user-1")
    await asyncio.sleep(0)

    persistence.save_and_emit.assert_not_awaited()
    payload = status_repo.write.call_args.args[1]
    assert payload["results"][0]["status"] == "failed"


async def test_below_threshold_written_as_failed_in_status(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
    status_repo: MagicMock,
) -> None:
    vc = _make_validated(confidence=0.20)
    pipeline.run = AsyncMock(return_value=[vc])
    persistence.save_and_emit = AsyncMock(return_value=[_below_threshold_outcome(vc)])

    await service.run("The Coffee Shop", user_id="user-1")
    await asyncio.sleep(0)

    payload = status_repo.write.call_args.args[1]
    assert payload["results"][0]["status"] == "failed"
    assert payload["results"][0]["place"] is None
    assert payload["results"][0]["confidence"] == pytest.approx(0.20)


async def test_tiktok_url_stamps_source_in_background(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
    status_repo: MagicMock,
) -> None:
    from totoro_ai.core.places import PlaceSource

    results = [_make_validated()]
    pipeline.run = AsyncMock(return_value=results)
    persistence.save_and_emit = AsyncMock(return_value=[_saved_outcome(results[0])])

    url = "https://www.tiktok.com/@user/video/123"
    await service.run(url, user_id="user-1")
    await asyncio.sleep(0)

    kw = persistence.save_and_emit.call_args.kwargs
    assert kw["source"] == PlaceSource.tiktok
    assert kw["source_url"] == url
