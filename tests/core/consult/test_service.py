"""Unit tests for ConsultService."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from totoro_ai.api.schemas.consult import ConsultResponse, Location
from totoro_ai.core.config import get_config
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.core.intent.intent_parser import ParsedIntent


@pytest.mark.asyncio
async def test_consult_service_returns_consult_response():
    """Test consult() returns ConsultResponse with reasoning steps and
    intent-derived summaries."""
    mock_llm = AsyncMock()
    mock_response = {
        "primary": {
            "place_name": "Ramen Yokocho",
            "address": "123 Sukhumvit Road, Bangkok",
            "reasoning": "Perfect ramen spot for a romantic date night",
        },
        "alternatives": [
            {
                "place_name": "Tonkotsu House",
                "address": "456 Sukhumvit Road, Bangkok",
                "reasoning": "Great tonkotsu broth, cozy atmosphere",
            },
            {
                "place_name": "Ramen Ya Osaka",
                "address": "789 Sukhumvit Road, Bangkok",
                "reasoning": "Authentic Osaka-style ramen",
            },
        ],
    }
    mock_llm.complete = AsyncMock(return_value=json.dumps(mock_response))
    service = ConsultService(llm=mock_llm)

    with patch("totoro_ai.core.consult.service.IntentParser") as mock_parser_class:
        mock_parser = AsyncMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse = AsyncMock(
            return_value=ParsedIntent(
                cuisine="ramen",
                occasion="date night",
                price_range=None,
                radius=None,
                constraints=[],
            )
        )

        result = await service.consult(
            user_id="test-user",
            query="good ramen for a date night",
            location=Location(lat=13.7563, lng=100.5018),
        )

        assert isinstance(result, ConsultResponse)
        assert result.primary is not None
        assert result.primary.place_name == "Ramen Yokocho"
        assert result.primary.address == "123 Sukhumvit Road, Bangkok"
        assert (
            "date night" in result.primary.reasoning.lower()
            or "ramen" in result.primary.reasoning.lower()
        )
        assert result.primary.photos is not None
        assert len(result.primary.photos) > 0

        # Verify exactly 2 alternatives from LLM
        assert len(result.alternatives) == 2
        assert result.alternatives[0].place_name == "Tonkotsu House"
        assert result.alternatives[1].place_name == "Ramen Ya Osaka"
        for alt in result.alternatives:
            assert alt.photos is not None
            assert len(alt.photos) > 0

        # Verify 6 reasoning steps in correct order
        assert len(result.reasoning_steps) == 6
        expected_steps = [
            "intent_parsing",
            "retrieval",
            "discovery",
            "validation",
            "ranking",
            "completion",
        ]
        for i, expected_step in enumerate(expected_steps):
            assert result.reasoning_steps[i].step == expected_step

        # Verify step summaries contain intent-derived values
        # (not "deferred" or phase language)
        # Step 0: intent_parsing should show parsed fields
        assert "Parsed:" in result.reasoning_steps[0].summary
        assert "ramen" in result.reasoning_steps[0].summary
        assert "date night" in result.reasoning_steps[0].summary

        # Step 1: retrieval - should mention ramen and location context
        assert "ramen" in result.reasoning_steps[1].summary
        assert "saved" in result.reasoning_steps[1].summary.lower()

        # Step 2: discovery - should mention ramen, location, and radius
        assert "ramen" in result.reasoning_steps[2].summary
        assert "km" in result.reasoning_steps[2].summary

        # Step 3: validation - should mention ramen
        assert "ramen" in result.reasoning_steps[3].summary

        # Step 4: ranking - should mention ramen and occasion
        assert "ramen" in result.reasoning_steps[4].summary
        assert "date night" in result.reasoning_steps[4].summary

        # Step 5: completion - should be completion text
        assert result.reasoning_steps[5].step == "completion"


@pytest.mark.asyncio
async def test_consult_service_with_venue_type() -> None:
    """Test consult() uses venue_type when cuisine is not specified."""
    mock_llm = AsyncMock()
    mock_response = {
        "primary": {
            "place_name": "Levels Club",
            "address": "Sukhumvit Soi 11, Bangkok",
            "reasoning": "Great rooftop club for a date",
        },
        "alternatives": [
            {
                "place_name": "Brick Bar",
                "address": "Khaosan Rd, Bangkok",
                "reasoning": "Cozy underground bar",
            },
            {
                "place_name": "The Club",
                "address": "Khaosan Rd, Bangkok",
                "reasoning": "Lively club with great music",
            },
        ],
    }
    mock_llm.complete = AsyncMock(return_value=json.dumps(mock_response))
    service = ConsultService(llm=mock_llm)

    with patch("totoro_ai.core.consult.service.IntentParser") as mock_parser_class:
        mock_parser = AsyncMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse = AsyncMock(
            return_value=ParsedIntent(
                cuisine=None,
                venue_type="club",
                occasion="date night",
                price_range=None,
                radius=None,
                constraints=[],
            )
        )

        result = await service.consult(
            user_id="test-user",
            query="good club for a date night",
            location=Location(lat=13.7563, lng=100.5018),
        )

        assert isinstance(result, ConsultResponse)
        assert result.primary.place_name == "Levels Club"
        assert result.primary.photos is not None
        assert len(result.alternatives) == 2

        # Verify venue_type is used in reasoning steps (not "restaurants")
        assert "club" in result.reasoning_steps[0].summary
        assert "club" in result.reasoning_steps[1].summary
        assert "club" in result.reasoning_steps[3].summary


@pytest.mark.asyncio
async def test_consult_service_without_location():
    """Test consult() works without location and uses fallback context."""
    mock_llm = AsyncMock()
    mock_response = {
        "primary": {
            "place_name": "Mario's Pizza",
            "address": "456 Main St, Your City",
            "reasoning": "Delicious pizza with fresh ingredients",
        },
        "alternatives": [
            {
                "place_name": "Bella Napoli",
                "address": "789 Main St, Your City",
                "reasoning": "Authentic Neapolitan pizza",
            },
            {
                "place_name": "Pizza House",
                "address": "321 Main St, Your City",
                "reasoning": "Classic pizza selections",
            },
        ],
    }
    mock_llm.complete = AsyncMock(return_value=json.dumps(mock_response))
    service = ConsultService(llm=mock_llm)

    with patch("totoro_ai.core.consult.service.IntentParser") as mock_parser_class:
        mock_parser = AsyncMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse = AsyncMock(
            return_value=ParsedIntent(
                cuisine="pizza",
                occasion=None,
                price_range=None,
                radius=None,
                constraints=[],
            )
        )

        result = await service.consult(
            user_id="test-user",
            query="good pizza",
        )

        assert isinstance(result, ConsultResponse)
        assert result.primary is not None
        assert result.primary.place_name == "Mario's Pizza"
        assert result.primary.address == "456 Main St, Your City"

        # Verify step summaries use fallback location ("nearby")
        # when not provided
        assert len(result.reasoning_steps) == 6
        assert "nearby" in result.reasoning_steps[1].summary
        assert "pizza" in result.reasoning_steps[1].summary


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

    # Verify LLM was called with messages format
    mock_llm.stream.assert_called_once_with(
        [
            {
                "role": "system",
                "content": "You are Totoro, an AI place recommendation assistant. Answer the user's query helpfully and concisely.",
            },
            {"role": "user", "content": "test query"},
        ]
    )


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
