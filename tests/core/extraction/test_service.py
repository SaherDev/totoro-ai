"""Tests for ExtractionService (T013 — Run 3 two-dep rewrite)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.api.schemas.extract_place import ExtractPlaceResponse
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.extraction.types import (
    ExtractionLevel,
    ExtractionResult,
    ProvisionalResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    place_name: str = "Fuji Ramen",
    address: str | None = "123 Sukhumvit",
    city: str | None = "Bangkok",
    cuisine: str | None = "ramen",
    confidence: float = 0.87,
    resolved_by: ExtractionLevel = ExtractionLevel.LLM_NER,
    external_id: str | None = "place_123",
    external_provider: str | None = "google",
) -> ExtractionResult:
    return ExtractionResult(
        place_name=place_name,
        address=address,
        city=city,
        cuisine=cuisine,
        confidence=confidence,
        resolved_by=resolved_by,
        corroborated=False,
        external_provider=external_provider,
        external_id=external_id,
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
    p.run = AsyncMock(return_value=[_make_result()])
    return p


@pytest.fixture
def persistence() -> MagicMock:
    ps = MagicMock()
    ps.save_and_emit = AsyncMock(return_value=["place-uuid-1"])
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
    """Empty string raises ValueError before hitting the pipeline."""
    with pytest.raises(ValueError, match="raw_input cannot be empty"):
        await service.run("", user_id="user-1")


async def test_whitespace_only_raw_input_raises_value_error(
    service: ExtractionService,
) -> None:
    """Whitespace-only input raises ValueError."""
    with pytest.raises(ValueError, match="raw_input cannot be empty"):
        await service.run("   ", user_id="user-1")


# ---------------------------------------------------------------------------
# Successful extraction — saved path
# ---------------------------------------------------------------------------


async def test_run_returns_extract_place_response(
    service: ExtractionService,
) -> None:
    """run() returns an ExtractPlaceResponse instance."""
    response = await service.run("Fuji Ramen Bangkok", user_id="user-1")

    assert isinstance(response, ExtractPlaceResponse)


async def test_run_saved_path_sets_provisional_false(
    service: ExtractionService,
) -> None:
    """When persistence returns IDs, provisional is False."""
    response = await service.run("Fuji Ramen Bangkok", user_id="user-1")

    assert response.provisional is False


async def test_run_saved_path_extraction_status_is_saved(
    service: ExtractionService,
) -> None:
    """When places are saved, extraction_status is 'saved'."""
    response = await service.run("Fuji Ramen Bangkok", user_id="user-1")

    assert response.extraction_status == "saved"


async def test_run_saved_path_places_length_matches_saved_ids(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    """places list length matches the number of saved IDs returned by persistence."""
    pipeline.run = AsyncMock(
        return_value=[_make_result("Place A"), _make_result("Place B")]
    )
    persistence.save_and_emit = AsyncMock(return_value=["uuid-a", "uuid-b"])

    response = await service.run("some input", user_id="user-1")

    assert len(response.places) == 2


async def test_run_saved_path_place_ids_from_persistence(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    """Each SavedPlace.place_id comes from the IDs returned by persistence."""
    pipeline.run = AsyncMock(return_value=[_make_result()])
    persistence.save_and_emit = AsyncMock(return_value=["expected-uuid"])

    response = await service.run("Fuji Ramen", user_id="user-1")

    assert response.places[0].place_id == "expected-uuid"


async def test_run_saved_path_place_fields_from_extraction_result(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    """SavedPlace fields are populated from ExtractionResult data."""
    result = _make_result(
        place_name="Ichiran",
        address="1 Hakata",
        city="Fukuoka",
        cuisine="ramen",
        confidence=0.92,
        resolved_by=ExtractionLevel.LLM_NER,
        external_provider="google",
        external_id="ichrn_001",
    )
    pipeline.run = AsyncMock(return_value=[result])
    persistence.save_and_emit = AsyncMock(return_value=["uuid-ichiran"])

    response = await service.run("Ichiran Fukuoka", user_id="user-1")

    place = response.places[0]
    assert place.place_name == "Ichiran"
    assert place.address == "1 Hakata"
    assert place.city == "Fukuoka"
    assert place.cuisine == "ramen"
    assert place.confidence == 0.92
    assert place.resolved_by == ExtractionLevel.LLM_NER.value
    assert place.external_provider == "google"
    assert place.external_id == "ichrn_001"


async def test_run_pending_levels_empty_on_saved_path(
    service: ExtractionService,
) -> None:
    """pending_levels is [] when extraction is saved (not provisional)."""
    response = await service.run("Fuji Ramen", user_id="user-1")

    assert response.pending_levels == []


# ---------------------------------------------------------------------------
# Dedup path — all duplicates
# ---------------------------------------------------------------------------


async def test_run_all_duplicates_extraction_status_is_duplicate(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    """When persistence returns [] (all duped), extraction_status is 'duplicate'."""
    pipeline.run = AsyncMock(return_value=[_make_result()])
    persistence.save_and_emit = AsyncMock(return_value=[])

    response = await service.run("Fuji Ramen", user_id="user-1")

    assert response.extraction_status == "duplicate"
    assert response.places == []
    assert response.provisional is False


# ---------------------------------------------------------------------------
# Provisional path
# ---------------------------------------------------------------------------


async def test_run_provisional_response_sets_provisional_true(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    """When pipeline returns ProvisionalResponse, provisional is True."""
    pipeline.run = AsyncMock(return_value=_make_provisional())

    response = await service.run(
        "https://tiktok.com/v/123", user_id="user-1"
    )

    assert response.provisional is True
    persistence.save_and_emit.assert_not_awaited()


async def test_run_provisional_response_places_is_empty(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    """ProvisionalResponse path returns empty places list."""
    pipeline.run = AsyncMock(return_value=_make_provisional())

    response = await service.run(
        "https://tiktok.com/v/123", user_id="user-1"
    )

    assert response.places == []


async def test_run_provisional_response_extraction_status_is_processing(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    """ProvisionalResponse path sets extraction_status to 'processing'."""
    pipeline.run = AsyncMock(return_value=_make_provisional())

    response = await service.run(
        "https://tiktok.com/v/123", user_id="user-1"
    )

    assert response.extraction_status == "processing"


async def test_run_provisional_pending_levels_populated(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    """pending_levels in response contains ExtractionLevel string values."""
    pending = [
        ExtractionLevel.SUBTITLE_CHECK,
        ExtractionLevel.WHISPER_AUDIO,
        ExtractionLevel.VISION_FRAMES,
    ]
    pipeline.run = AsyncMock(return_value=_make_provisional(pending_levels=pending))

    response = await service.run(
        "https://tiktok.com/v/123", user_id="user-1"
    )

    assert set(response.pending_levels) == {
        ExtractionLevel.SUBTITLE_CHECK.value,
        ExtractionLevel.WHISPER_AUDIO.value,
        ExtractionLevel.VISION_FRAMES.value,
    }


# ---------------------------------------------------------------------------
# Pipeline delegation — URL and supplementary_text forwarding
# ---------------------------------------------------------------------------


async def test_pipeline_called_with_url_from_parsed_input(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    """pipeline.run receives the URL extracted from raw_input."""
    await service.run(
        "https://tiktok.com/v/999 great ramen spot", user_id="user-1"
    )

    call_kwargs = pipeline.run.call_args
    assert call_kwargs.kwargs["url"] == "https://tiktok.com/v/999"


async def test_pipeline_called_with_supplementary_text(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    """pipeline.run receives the supplementary text stripped from raw_input."""
    await service.run(
        "https://tiktok.com/v/999 great ramen spot", user_id="user-1"
    )

    call_kwargs = pipeline.run.call_args
    assert call_kwargs.kwargs["supplementary_text"] == "great ramen spot"


async def test_pipeline_called_with_user_id(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    """pipeline.run receives the user_id passed to service.run."""
    await service.run("Fuji Ramen", user_id="user-42")

    call_kwargs = pipeline.run.call_args
    assert call_kwargs.kwargs["user_id"] == "user-42"


async def test_pipeline_called_with_url_none_for_plain_text(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    """For plain text input (no URL), pipeline.run gets url=None."""
    await service.run("Fuji Ramen Bangkok no URL", user_id="user-1")

    call_kwargs = pipeline.run.call_args
    assert call_kwargs.kwargs["url"] is None


# ---------------------------------------------------------------------------
# source_url in response
# ---------------------------------------------------------------------------


async def test_source_url_set_to_parsed_url_on_saved_path(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    """source_url in response reflects the URL parsed from raw_input."""
    pipeline.run = AsyncMock(return_value=[_make_result()])
    persistence.save_and_emit = AsyncMock(return_value=["uuid-1"])

    response = await service.run(
        "https://tiktok.com/v/abc check this out", user_id="user-1"
    )

    assert response.source_url == "https://tiktok.com/v/abc"


async def test_source_url_none_for_plain_text_input(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    """source_url is None when raw_input contains no URL."""
    pipeline.run = AsyncMock(return_value=[_make_result()])
    persistence.save_and_emit = AsyncMock(return_value=["uuid-1"])

    response = await service.run("Fuji Ramen no url", user_id="user-1")

    assert response.source_url is None


async def test_source_url_set_on_provisional_path(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    """source_url in provisional response reflects the parsed URL."""
    pipeline.run = AsyncMock(return_value=_make_provisional())

    response = await service.run(
        "https://tiktok.com/v/xyz", user_id="user-1"
    )

    assert response.source_url == "https://tiktok.com/v/xyz"


# ---------------------------------------------------------------------------
# Persistence delegation
# ---------------------------------------------------------------------------


async def test_persistence_called_with_pipeline_results(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    """persistence.save_and_emit is called with the list returned by pipeline."""
    results = [_make_result()]
    pipeline.run = AsyncMock(return_value=results)
    persistence.save_and_emit = AsyncMock(return_value=["uuid-1"])

    await service.run("Fuji Ramen", user_id="user-1")

    persistence.save_and_emit.assert_awaited_once_with(results, "user-1")


async def test_persistence_not_called_on_provisional_path(
    service: ExtractionService,
    pipeline: MagicMock,
    persistence: MagicMock,
) -> None:
    """save_and_emit is NOT called when pipeline returns ProvisionalResponse.

    Provisional means no inline candidates found — persistence is not invoked.
    """
    pipeline.run = AsyncMock(return_value=_make_provisional())

    await service.run("https://tiktok.com/v/123", user_id="user-1")

    persistence.save_and_emit.assert_not_awaited()


# ---------------------------------------------------------------------------
# request_id forwarding (Run 4 — status polling)
# ---------------------------------------------------------------------------


async def test_provisional_response_carries_request_id(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    """ProvisionalResponse.request_id is forwarded to ExtractPlaceResponse."""
    provisional = _make_provisional()
    provisional.request_id = "550e8400-e29b-41d4-a716-446655440000"
    pipeline.run = AsyncMock(return_value=provisional)

    response = await service.run("https://tiktok.com/v/123", user_id="user-1")

    assert response.request_id == "550e8400-e29b-41d4-a716-446655440000"


async def test_provisional_response_request_id_empty_string_becomes_none(
    service: ExtractionService,
    pipeline: MagicMock,
) -> None:
    """Empty string request_id (default) becomes None in API response."""
    provisional = _make_provisional()
    provisional.request_id = ""  # default value
    pipeline.run = AsyncMock(return_value=provisional)

    response = await service.run("https://tiktok.com/v/123", user_id="user-1")

    assert response.request_id is None


async def test_saved_path_request_id_is_none(
    service: ExtractionService,
) -> None:
    """Synchronous saved path always returns request_id=None."""
    response = await service.run("Fuji Ramen Bangkok", user_id="user-1")

    assert response.request_id is None
