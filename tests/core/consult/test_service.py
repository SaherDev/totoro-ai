"""Unit tests for ConsultService."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.api.schemas.consult import Location, SyncConsultResponse
from totoro_ai.core.consult.service import SYSTEM_PROMPT, ConsultService


@pytest.mark.asyncio
async def test_consult_service_returns_sync_response():
    """Test that consult() returns SyncConsultResponse with correct structure."""
    mock_llm = AsyncMock()
    service = ConsultService(llm=mock_llm)

    result = await service.consult(
        user_id="test-user",
        query="test query",
        location=Location(lat=0.0, lng=0.0),
    )

    assert isinstance(result, SyncConsultResponse)
    assert result.primary is not None
    assert result.primary.place_name == "Stub Place"
    assert result.primary.address == "123 Test St"
    assert len(result.reasoning_steps) == 2
    assert result.reasoning_steps[0].step == "intent_parsing"
    assert result.reasoning_steps[1].step == "ranking"


@pytest.mark.asyncio
async def test_consult_service_without_location():
    """Test consult() works without location parameter."""
    mock_llm = AsyncMock()
    service = ConsultService(llm=mock_llm)

    result = await service.consult(
        user_id="test-user",
        query="test query",
    )

    assert isinstance(result, SyncConsultResponse)
    assert result.primary.place_name == "Stub Place"


@pytest.mark.asyncio
async def test_stream_yields_token_events():
    """Test that stream() yields tokens as SSE events."""
    mock_llm = AsyncMock()

    # Mock the async generator
    async def mock_stream_generator(*args):
        yield "Hello"
        yield " "
        yield "world"

    mock_llm.stream = MagicMock(return_value=mock_stream_generator())

    service = ConsultService(llm=mock_llm)

    # Mock request object
    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    events = []
    async for event in service.stream(
        user_id="test-user",
        query="test query",
        request=mock_request,
    ):
        events.append(event)

    # Should have 3 tokens + 1 done event
    assert len(events) == 4

    # Parse token events
    token1 = json.loads(events[0].replace("data: ", ""))
    token2 = json.loads(events[1].replace("data: ", ""))
    token3 = json.loads(events[2].replace("data: ", ""))

    assert token1 == {"token": "Hello"}
    assert token2 == {"token": " "}
    assert token3 == {"token": "world"}

    # Last event should be done
    done_event = json.loads(events[3].replace("data: ", ""))
    assert done_event == {"done": True}


@pytest.mark.asyncio
async def test_stream_calls_llm_with_system_prompt():
    """Test that stream() calls LLM with correct system prompt."""
    mock_llm = AsyncMock()

    async def mock_stream_generator(*args):
        yield "token"

    mock_llm.stream = MagicMock(return_value=mock_stream_generator())

    service = ConsultService(llm=mock_llm)

    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    async for _ in service.stream(
        user_id="test-user",
        query="test query",
        request=mock_request,
    ):
        pass

    # Verify LLM was called with system prompt and query
    mock_llm.stream.assert_called_once_with(SYSTEM_PROMPT, "test query")
    expected_prompt = (
        "You are Totoro, an AI place recommendation assistant. "
        "Answer the user's query helpfully and concisely."
    )
    assert expected_prompt == SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_stream_detects_disconnect():
    """Test that stream() breaks iteration on client disconnect."""
    mock_llm = AsyncMock()

    # Mock generator that yields many tokens
    async def mock_stream_generator(*args):
        for i in range(100):
            yield f"token_{i}"

    mock_llm.stream = MagicMock(return_value=mock_stream_generator())

    service = ConsultService(llm=mock_llm)

    # Mock request that detects disconnect after 2 tokens
    mock_request = AsyncMock()
    disconnect_calls = [False, False, True, True]  # Disconnect on 3rd token
    mock_request.is_disconnected = AsyncMock(side_effect=disconnect_calls)

    events = []
    async for event in service.stream(
        user_id="test-user",
        query="test query",
        request=mock_request,
    ):
        events.append(event)

    # Should only have 2 token events (breaks before 3rd)
    # No done event because client disconnected
    assert len(events) == 2
    token1 = json.loads(events[0].replace("data: ", ""))
    token2 = json.loads(events[1].replace("data: ", ""))
    assert token1["token"] == "token_0"
    assert token2["token"] == "token_1"


@pytest.mark.asyncio
async def test_stream_no_done_event_on_disconnect():
    """Test that done event is not sent if client disconnected."""
    mock_llm = AsyncMock()

    async def mock_stream_generator(*args):
        yield "token"

    mock_llm.stream = MagicMock(return_value=mock_stream_generator())

    service = ConsultService(llm=mock_llm)

    # Mock request that is disconnected before checking for done event
    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(side_effect=[False, True])

    events = []
    async for event in service.stream(
        user_id="test-user",
        query="test query",
        request=mock_request,
    ):
        events.append(event)

    # Should only have token event, no done event
    assert len(events) == 1
    token = json.loads(events[0].replace("data: ", ""))
    assert token == {"token": "token"}
