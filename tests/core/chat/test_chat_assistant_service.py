"""Unit tests for ChatAssistantService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from totoro_ai.api.errors import LLMUnavailableError
from totoro_ai.core.chat.chat_assistant_service import (
    ChatAssistantService,
)


@patch(
    "totoro_ai.core.chat.chat_assistant_service.get_langfuse_client", return_value=None
)
@patch("totoro_ai.core.chat.chat_assistant_service.get_llm")
async def test_run_happy_path(
    mock_get_llm: MagicMock, mock_langfuse: MagicMock
) -> None:
    """Service returns the LLM response string on success."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = "Tokyo is outstanding for food."
    mock_get_llm.return_value = mock_llm

    memory = MagicMock()
    memory.load_memories = AsyncMock(return_value=[])
    service = ChatAssistantService(memory_service=memory)
    result = await service.run("What do you think about Tokyo for food?", "user_123")

    assert result == "Tokyo is outstanding for food."
    mock_llm.complete.assert_called_once()


@patch(
    "totoro_ai.core.chat.chat_assistant_service.get_langfuse_client", return_value=None
)
@patch("totoro_ai.core.chat.chat_assistant_service.get_llm")
async def test_run_llm_failure_raises_llm_unavailable_error(
    mock_get_llm: MagicMock, mock_langfuse: MagicMock
) -> None:
    """LLM exception is wrapped in LLMUnavailableError."""
    mock_llm = AsyncMock()
    mock_llm.complete.side_effect = RuntimeError("timeout")
    mock_get_llm.return_value = mock_llm

    memory = MagicMock()
    memory.load_memories = AsyncMock(return_value=[])
    service = ChatAssistantService(memory_service=memory)
    with pytest.raises(LLMUnavailableError, match="timeout"):
        await service.run("What do you think about Tokyo for food?", "user_123")


@patch("totoro_ai.core.chat.chat_assistant_service.get_llm")
async def test_run_tracks_langfuse_generation(mock_get_llm: MagicMock) -> None:
    """Langfuse generation.end() is called after a successful run."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = "Go to Tokyo."
    mock_get_llm.return_value = mock_llm

    mock_generation = MagicMock()
    mock_lf = MagicMock()
    mock_lf.generation.return_value = mock_generation

    with patch(
        "totoro_ai.core.chat.chat_assistant_service.get_langfuse_client",
        return_value=mock_lf,
    ):
        memory = MagicMock()
        memory.load_memories = AsyncMock(return_value=[])
        service = ChatAssistantService(memory_service=memory)
        await service.run("Tokyo food?", "user_123")

    mock_lf.generation.assert_called_once_with(
        name="chat_assistant",
        input={"user_id": "user_123", "message": "Tokyo food?"},
    )
    mock_generation.end.assert_called_once()


@patch(
    "totoro_ai.core.chat.chat_assistant_service.get_langfuse_client", return_value=None
)
@patch("totoro_ai.core.chat.chat_assistant_service.get_llm")
async def test_system_prompt_passed_to_llm(
    mock_get_llm: MagicMock, mock_langfuse: MagicMock
) -> None:
    """System prompt is the first message and includes key persona signals."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = "Yes, go for omakase."
    mock_get_llm.return_value = mock_llm

    memory = MagicMock()
    memory.load_memories = AsyncMock(return_value=[])
    service = ChatAssistantService(memory_service=memory)
    await service.run("Is omakase worth it?", "user_123")

    call_args = mock_llm.complete.call_args
    messages = call_args[0][0]

    assert messages[0]["role"] == "system"
    system_content = messages[0]["content"]
    assert "opinionated" in system_content.lower() or "direct" in system_content.lower()
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Is omakase worth it?"
