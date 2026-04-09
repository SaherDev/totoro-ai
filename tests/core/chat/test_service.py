"""Unit tests for ChatService.run() dispatch paths."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from totoro_ai.api.schemas.chat import ChatRequest
from totoro_ai.api.schemas.consult import (
    ConsultResponse,
    Location,
    PlaceResult,
    ReasoningStep,
)
from totoro_ai.api.schemas.extract_place import ExtractPlaceResponse, SavedPlace
from totoro_ai.api.schemas.recall import RecallResponse, RecallResult
from totoro_ai.core.chat.router import IntentClassification
from totoro_ai.core.chat.service import ChatService


def _make_service(
    extraction: AsyncMock | None = None,
    consult: AsyncMock | None = None,
    recall: AsyncMock | None = None,
    assistant: AsyncMock | None = None,
) -> ChatService:
    """Helper to build a ChatService with all deps mocked."""
    return ChatService(
        extraction_service=extraction or AsyncMock(),
        consult_service=consult or AsyncMock(),
        recall_service=recall or AsyncMock(),
        assistant_service=assistant or AsyncMock(),
    )


def _consult_response() -> ConsultResponse:
    return ConsultResponse(
        primary=PlaceResult(
            place_name="Nara Eatery",
            address="123 Test St",
            reasoning="Great ramen",
            source="saved",
        ),
        alternatives=[],
        reasoning_steps=[ReasoningStep(step="1", summary="Recalled from memory")],
    )


def _extract_response() -> ExtractPlaceResponse:
    return ExtractPlaceResponse(
        provisional=False,
        places=[
            SavedPlace(
                place_id="place-1",
                place_name="Ichiran Ramen",
                address="Shibuya",
                city="Tokyo",
                cuisine="ramen",
                confidence=0.9,
                resolved_by="google",
                external_provider="google",
                external_id="ChIJxxx",
                extraction_status="saved",
            )
        ],
        pending_levels=[],
        extraction_status="saved",
        source_url=None,
    )


def _recall_response() -> RecallResponse:
    return RecallResponse(
        results=[
            RecallResult(
                place_id="place-1",
                place_name="Ichiran Ramen",
                address="Shibuya",
                saved_at=datetime(2024, 1, 1, tzinfo=UTC),
                match_reason="vector",
            )
        ],
        total=1,
        empty_state=False,
    )


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_consult_intent(mock_classify: MagicMock) -> None:
    """ChatService routes 'consult' intent to ConsultService."""
    mock_classify.return_value = IntentClassification(
        intent="consult", confidence=0.95, clarification_needed=False
    )
    consult_mock = AsyncMock()
    consult_mock.consult.return_value = _consult_response()

    service = _make_service(consult=consult_mock)
    request = ChatRequest(user_id="user_1", message="cheap dinner nearby")

    result = await service.run(request)

    assert result.type == "consult"
    assert result.data is not None
    consult_mock.consult.assert_called_once_with("user_1", "cheap dinner nearby", None)


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_extract_place_intent(mock_classify: MagicMock) -> None:
    """ChatService routes 'extract-place' intent to ExtractionService."""
    mock_classify.return_value = IntentClassification(
        intent="extract-place", confidence=0.98, clarification_needed=False
    )
    extraction_mock = AsyncMock()
    extraction_mock.run.return_value = _extract_response()

    service = _make_service(extraction=extraction_mock)
    request = ChatRequest(user_id="user_1", message="https://www.tiktok.com/video/123")

    result = await service.run(request)

    assert result.type == "extract-place"
    assert result.data is not None
    extraction_mock.run.assert_called_once_with(
        "https://www.tiktok.com/video/123", "user_1"
    )


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_recall_intent(mock_classify: MagicMock) -> None:
    """ChatService routes 'recall' intent to RecallService."""
    mock_classify.return_value = IntentClassification(
        intent="recall", confidence=0.90, clarification_needed=False
    )
    recall_mock = AsyncMock()
    recall_mock.run.return_value = _recall_response()

    service = _make_service(recall=recall_mock)
    request = ChatRequest(user_id="user_1", message="that ramen place I saved")

    result = await service.run(request)

    assert result.type == "recall"
    assert result.data is not None
    recall_mock.run.assert_called_once_with("that ramen place I saved", "user_1")


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_assistant_intent(mock_classify: MagicMock) -> None:
    """ChatService routes 'assistant' intent to ChatAssistantService."""
    mock_classify.return_value = IntentClassification(
        intent="assistant", confidence=0.92, clarification_needed=False
    )
    assistant_mock = AsyncMock()
    assistant_mock.run.return_value = "Tipping is not expected in Japan."

    service = _make_service(assistant=assistant_mock)
    request = ChatRequest(user_id="user_1", message="is tipping expected in Japan?")

    result = await service.run(request)

    assert result.type == "assistant"
    assert result.message == "Tipping is not expected in Japan."
    assert result.data is None
    assistant_mock.run.assert_called_once_with(
        "is tipping expected in Japan?", "user_1"
    )


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_error_on_downstream_exception(mock_classify: MagicMock) -> None:
    """ChatService returns type='error' when downstream service raises."""
    mock_classify.return_value = IntentClassification(
        intent="consult", confidence=0.95, clarification_needed=False
    )
    consult_mock = AsyncMock()
    consult_mock.consult.side_effect = RuntimeError("DB timeout")

    service = _make_service(consult=consult_mock)
    request = ChatRequest(user_id="user_1", message="cheap dinner nearby")

    result = await service.run(request)

    assert result.type == "error"
    assert "DB timeout" in (result.data or {}).get("detail", "")


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_error_on_classify_exception(mock_classify: MagicMock) -> None:
    """ChatService returns type='error' when classify_intent raises."""
    mock_classify.side_effect = RuntimeError("LLM timeout")

    service = _make_service()
    request = ChatRequest(user_id="user_1", message="something")

    result = await service.run(request)

    assert result.type == "error"


# Phase 4 / US2 — clarification (T014)


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_clarification_response_no_downstream_call(
    mock_classify: MagicMock,
) -> None:
    """ChatService returns clarification without calling any downstream service."""
    mock_classify.return_value = IntentClassification(
        intent="recall",
        confidence=0.48,
        clarification_needed=True,
        clarification_question=(
            "Are you looking for a saved place called Fuji or a recommendation?"
        ),
    )
    consult_mock = AsyncMock()
    recall_mock = AsyncMock()
    extraction_mock = AsyncMock()
    assistant_mock = AsyncMock()

    service = _make_service(
        extraction=extraction_mock,
        consult=consult_mock,
        recall=recall_mock,
        assistant=assistant_mock,
    )
    request = ChatRequest(user_id="user_1", message="fuji")

    result = await service.run(request)

    assert result.type == "clarification"
    assert result.data is None
    assert "Fuji" in result.message or "fuji" in result.message.lower()

    consult_mock.consult.assert_not_called()
    recall_mock.run.assert_not_called()
    extraction_mock.run.assert_not_called()
    assistant_mock.run.assert_not_called()


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_consult_passes_location(mock_classify: MagicMock) -> None:
    """ChatService passes location to ConsultService.consult() call."""
    mock_classify.return_value = IntentClassification(
        intent="consult", confidence=0.95, clarification_needed=False
    )
    consult_mock = AsyncMock()
    consult_mock.consult.return_value = _consult_response()

    service = _make_service(consult=consult_mock)
    loc = Location(lat=13.7563, lng=100.5018)
    request = ChatRequest(user_id="user_1", message="cheap dinner nearby", location=loc)

    await service.run(request)

    consult_mock.consult.assert_called_once_with("user_1", "cheap dinner nearby", loc)
