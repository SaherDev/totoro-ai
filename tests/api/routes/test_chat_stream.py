"""Tests for POST /v1/chat/stream SSE endpoint (feature 028 M7)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from totoro_ai.api.deps import get_agent_graph, get_chat_service
from totoro_ai.api.main import app
from totoro_ai.core.agent.reasoning import ReasoningStep
from totoro_ai.core.chat.service import ChatService
from totoro_ai.core.config import AgentConfig, AppConfig


def _make_mock_config(enabled: bool = True) -> MagicMock:
    """Build a mock AppConfig where agent.enabled is `enabled`."""
    cfg = MagicMock(spec=AppConfig)
    agent_cfg = MagicMock(spec=AgentConfig)
    agent_cfg.enabled = enabled
    cfg.agent = agent_cfg
    return cfg


def _make_mock_service(enabled: bool = True) -> MagicMock:
    """Build a mock ChatService with async taste/memory helpers."""
    svc = MagicMock(spec=ChatService)
    svc._config = _make_mock_config(enabled=enabled)
    svc._compose_taste_summary = AsyncMock(return_value="")
    svc._compose_memory_summary = AsyncMock(return_value="")
    return svc


def _make_step_event(step: str, summary: str) -> dict[str, Any]:
    rs = ReasoningStep(
        step=step,
        summary=summary,
        source="tool",
        tool_name="recall",
        visibility="debug",
    )
    return {
        "event": "on_custom_event",
        "name": "stream",
        "data": rs.model_dump(mode="json"),
    }


@pytest.fixture
def mock_service() -> MagicMock:
    return _make_mock_service(enabled=True)


@pytest.fixture
def mock_graph() -> MagicMock:
    """Fake compiled graph with astream_events."""
    graph = MagicMock()

    async def _stream_events(
        payload: Any, config: Any, version: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        yield _make_step_event("recall.search", "searching saves")
        from langchain_core.messages import AIMessage

        yield {
            "event": "on_chain_end",
            "data": {
                "output": {"messages": [AIMessage(content="Here is my recommendation")]}
            },
        }

    graph.astream_events = _stream_events
    return graph


@pytest.fixture
def client(mock_service: MagicMock, mock_graph: MagicMock) -> TestClient:
    app.dependency_overrides[get_chat_service] = lambda: mock_service
    app.dependency_overrides[get_agent_graph] = lambda: mock_graph
    yield TestClient(app)
    app.dependency_overrides.pop(get_chat_service, None)
    app.dependency_overrides.pop(get_agent_graph, None)


class TestChatStreamHappyPath:
    """Verify POST /v1/chat/stream returns SSE frames for the agent path."""

    def test_stream_returns_200(self, client: TestClient) -> None:
        response = client.post(
            "/v1/chat/stream",
            json={"user_id": "u1", "message": "dinner nearby"},
            headers={"Accept": "text/event-stream"},
        )
        assert response.status_code == 200

    def test_stream_content_type_is_event_stream(self, client: TestClient) -> None:
        response = client.post(
            "/v1/chat/stream",
            json={"user_id": "u1", "message": "dinner nearby"},
        )
        assert "text/event-stream" in response.headers["content-type"]

    def test_stream_contains_reasoning_step_frame(self, client: TestClient) -> None:
        response = client.post(
            "/v1/chat/stream",
            json={"user_id": "u1", "message": "dinner nearby"},
        )
        assert "event: reasoning_step" in response.text

    def test_stream_contains_message_frame(self, client: TestClient) -> None:
        response = client.post(
            "/v1/chat/stream",
            json={"user_id": "u1", "message": "dinner nearby"},
        )
        assert "event: message" in response.text
        assert "Here is my recommendation" in response.text

    def test_reasoning_step_frame_has_expected_shape(self, client: TestClient) -> None:
        """reasoning_step frames contain step, summary, source, tool_name fields."""
        import json

        response = client.post(
            "/v1/chat/stream",
            json={"user_id": "u1", "message": "dinner nearby"},
        )
        lines = response.text.splitlines()
        step_data: dict[str, Any] | None = None
        for i, line in enumerate(lines):
            if line.startswith("event: reasoning_step"):
                # look at the next data line
                for j in range(i + 1, min(i + 3, len(lines))):
                    if lines[j].startswith("data: "):
                        step_data = json.loads(lines[j][len("data: ") :])
                        break
                break

        assert step_data is not None
        assert "step" in step_data
        assert "summary" in step_data
        assert "source" in step_data

    def test_stream_message_frame_has_content_key(self, client: TestClient) -> None:
        import json

        response = client.post(
            "/v1/chat/stream",
            json={"user_id": "u1", "message": "dinner nearby"},
        )
        lines = response.text.splitlines()
        msg_data: dict[str, Any] | None = None
        for i, line in enumerate(lines):
            if line.startswith("event: message"):
                for j in range(i + 1, min(i + 3, len(lines))):
                    if lines[j].startswith("data: "):
                        msg_data = json.loads(lines[j][len("data: ") :])
                        break
                break

        assert msg_data is not None
        assert "content" in msg_data
        assert msg_data["content"] == "Here is my recommendation"


class TestChatStreamDisabledAgent:
    """Verify /v1/chat/stream returns 400 when agent is disabled or graph is None."""

    def test_returns_400_when_agent_disabled(self) -> None:
        disabled_svc = _make_mock_service(enabled=False)
        app.dependency_overrides[get_chat_service] = lambda: disabled_svc
        app.dependency_overrides[get_agent_graph] = lambda: MagicMock()
        try:
            tc = TestClient(app)
            response = tc.post(
                "/v1/chat/stream",
                json={"user_id": "u1", "message": "test"},
            )
            assert response.status_code == 400
        finally:
            app.dependency_overrides.pop(get_chat_service, None)
            app.dependency_overrides.pop(get_agent_graph, None)

    def test_returns_400_when_graph_is_none(self) -> None:
        enabled_svc = _make_mock_service(enabled=True)
        app.dependency_overrides[get_chat_service] = lambda: enabled_svc
        app.dependency_overrides[get_agent_graph] = lambda: None
        try:
            tc = TestClient(app)
            response = tc.post(
                "/v1/chat/stream",
                json={"user_id": "u1", "message": "test"},
            )
            assert response.status_code == 400
        finally:
            app.dependency_overrides.pop(get_chat_service, None)
            app.dependency_overrides.pop(get_agent_graph, None)
