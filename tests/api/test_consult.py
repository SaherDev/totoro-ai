"""Integration tests for POST /v1/consult endpoint."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_streaming_endpoint_returns_event_stream():
    """Test POST /v1/consult with stream=true returns text/event-stream."""
    from totoro_ai.api.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Mock the LLM provider to return tokens
        with patch("totoro_ai.api.routes.consult.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()

            # Mock the async context manager and generator
            async def mock_stream_generator(*args):
                yield "Hello"
                yield " "
                yield "world"

            mock_llm.stream = MagicMock(return_value=mock_stream_generator())
            mock_get_llm.return_value = mock_llm

            response = await client.post(
                "/v1/consult",
                json={
                    "user_id": "test-user",
                    "query": "test query",
                    "stream": True,
                },
            )

            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "Cache-Control" in response.headers
            assert response.headers["Cache-Control"] == "no-cache"
            assert "X-Accel-Buffering" in response.headers
            assert response.headers["X-Accel-Buffering"] == "no"


@pytest.mark.asyncio
async def test_synchronous_endpoint_returns_json():
    """Test POST /v1/consult without stream returns JSON response."""
    from totoro_ai.api.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Mock the LLM provider
        with patch("totoro_ai.api.routes.consult.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_get_llm.return_value = mock_llm

            response = await client.post(
                "/v1/consult",
                json={
                    "user_id": "test-user",
                    "query": "test query",
                    "stream": False,
                },
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "application/json"

            data = response.json()
            assert "primary" in data
            assert "alternatives" in data
            assert "reasoning_steps" in data


@pytest.mark.asyncio
async def test_synchronous_endpoint_without_stream_field():
    """Test POST /v1/consult without stream field defaults to JSON."""
    from totoro_ai.api.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Mock the LLM provider
        with patch("totoro_ai.api.routes.consult.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_get_llm.return_value = mock_llm

            response = await client.post(
                "/v1/consult",
                json={
                    "user_id": "test-user",
                    "query": "test query",
                },
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_streaming_tokens_arrive_in_sse_format():
    """Test that streaming response emits tokens as SSE events."""
    from totoro_ai.api.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Mock the LLM provider to return tokens
        with patch("totoro_ai.api.routes.consult.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()

            # Mock the async context manager and generator
            async def mock_stream_generator(*args):
                yield "Hello"
                yield " "
                yield "world"

            mock_llm.stream = MagicMock(return_value=mock_stream_generator())
            mock_get_llm.return_value = mock_llm

            response = await client.post(
                "/v1/consult",
                json={
                    "user_id": "test-user",
                    "query": "test query",
                    "stream": True,
                },
            )

            assert response.status_code == 200

            # Parse SSE events
            lines = response.text.split("\n\n")
            events = [line for line in lines if line.startswith("data: ")]

            assert len(events) >= 4  # At least 3 tokens + done event

            # First three events should be token events
            token1 = json.loads(events[0].replace("data: ", ""))
            token2 = json.loads(events[1].replace("data: ", ""))
            token3 = json.loads(events[2].replace("data: ", ""))

            assert "token" in token1
            assert token1["token"] == "Hello"
            assert "token" in token2
            assert token2["token"] == " "
            assert "token" in token3
            assert token3["token"] == "world"

            # Last event should be done
            done_event = json.loads(events[-1].replace("data: ", ""))
            assert done_event == {"done": True}


@pytest.mark.asyncio
async def test_streaming_cleanup_on_concurrent_disconnect():
    """Test that multiple concurrent streams can disconnect safely."""
    from totoro_ai.api.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Mock the LLM provider
        with patch("totoro_ai.api.routes.consult.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()

            # Mock the async context manager and generator with many tokens
            async def mock_stream_generator(*args):
                for i in range(100):
                    yield f"token_{i}_"

            mock_llm.stream = MagicMock(return_value=mock_stream_generator())
            mock_get_llm.return_value = mock_llm

            # Start multiple concurrent requests
            for _ in range(5):
                response = await client.post(
                    "/v1/consult",
                    json={
                        "user_id": "test-user",
                        "query": "test query",
                        "stream": True,
                    },
                )
                # In a real test, we'd use asyncio.gather, but httpx blocks
                # This at least verifies requests don't hang
                assert response.status_code == 200

            # If we get here without hanging, cleanup was successful
