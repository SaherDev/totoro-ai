"""Unit tests for classify_intent in core/chat/router.py."""

from unittest.mock import AsyncMock, MagicMock, patch

from totoro_ai.core.chat.router import IntentClassification, classify_intent


@patch("totoro_ai.core.chat.router.get_langfuse_client", return_value=None)
@patch("totoro_ai.core.chat.router.get_llm")
async def test_classify_intent_consult(
    mock_get_llm: MagicMock, mock_langfuse: MagicMock
) -> None:
    """classify_intent returns 'consult' intent for a recommendation message."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = (
        '{"intent": "consult", "confidence": 0.95, '
        '"clarification_needed": false, "clarification_question": null}'
    )
    mock_get_llm.return_value = mock_llm

    result = await classify_intent("cheap dinner nearby")

    assert result.intent == "consult"
    assert result.confidence == 0.95
    assert result.clarification_needed is False
    assert result.clarification_question is None


@patch("totoro_ai.core.chat.router.get_langfuse_client", return_value=None)
@patch("totoro_ai.core.chat.router.get_llm")
async def test_classify_intent_extract_place(
    mock_get_llm: MagicMock, mock_langfuse: MagicMock
) -> None:
    """classify_intent returns 'extract-place' for a TikTok URL message."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = (
        '{"intent": "extract-place", "confidence": 0.98, '
        '"clarification_needed": false, "clarification_question": null}'
    )
    mock_get_llm.return_value = mock_llm

    result = await classify_intent("https://www.tiktok.com/@user/video/123456")

    assert result.intent == "extract-place"
    assert result.confidence == 0.98
    assert result.clarification_needed is False


@patch("totoro_ai.core.chat.router.get_langfuse_client", return_value=None)
@patch("totoro_ai.core.chat.router.get_llm")
async def test_classify_intent_recall(
    mock_get_llm: MagicMock, mock_langfuse: MagicMock
) -> None:
    """classify_intent returns 'recall' for a saved-places lookup."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = (
        '{"intent": "recall", "confidence": 0.90, '
        '"clarification_needed": false, "clarification_question": null}'
    )
    mock_get_llm.return_value = mock_llm

    result = await classify_intent("that ramen place I saved from TikTok")

    assert result.intent == "recall"
    assert result.confidence == 0.90
    assert result.clarification_needed is False


@patch("totoro_ai.core.chat.router.get_langfuse_client", return_value=None)
@patch("totoro_ai.core.chat.router.get_llm")
async def test_classify_intent_assistant(
    mock_get_llm: MagicMock, mock_langfuse: MagicMock
) -> None:
    """classify_intent returns 'assistant' for a general food question."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = (
        '{"intent": "assistant", "confidence": 0.92, '
        '"clarification_needed": false, "clarification_question": null}'
    )
    mock_get_llm.return_value = mock_llm

    result = await classify_intent("is tipping expected in Japan?")

    assert result.intent == "assistant"
    assert result.clarification_needed is False


@patch("totoro_ai.core.chat.router.get_langfuse_client", return_value=None)
@patch("totoro_ai.core.chat.router.get_llm")
async def test_classify_intent_strips_markdown_fences(
    mock_get_llm: MagicMock, mock_langfuse: MagicMock
) -> None:
    """classify_intent strips ```json ... ``` wrappers from malformed responses."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = (
        "```json\n"
        '{"intent": "consult", "confidence": 0.88, '
        '"clarification_needed": false, "clarification_question": null}\n'
        "```"
    )
    mock_get_llm.return_value = mock_llm

    result = await classify_intent("best sushi in Bangkok")

    assert result.intent == "consult"
    assert result.confidence == 0.88


@patch("totoro_ai.core.chat.router.get_langfuse_client", return_value=None)
@patch("totoro_ai.core.chat.router.get_llm")
async def test_classify_intent_strips_plain_fences(
    mock_get_llm: MagicMock, mock_langfuse: MagicMock
) -> None:
    """classify_intent strips plain ``` ... ``` wrappers (no json tag)."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = (
        "```\n"
        '{"intent": "assistant", "confidence": 0.80, '
        '"clarification_needed": false, "clarification_question": null}\n'
        "```"
    )
    mock_get_llm.return_value = mock_llm

    result = await classify_intent("what is pad see ew?")

    assert result.intent == "assistant"


# Phase 4 / US2 — low confidence tests (T013)


@patch("totoro_ai.core.chat.router.get_langfuse_client", return_value=None)
@patch("totoro_ai.core.chat.router.get_llm")
async def test_classify_intent_low_confidence_clarification_needed(
    mock_get_llm: MagicMock, mock_langfuse: MagicMock
) -> None:
    """classify_intent sets clarification_needed=True when confidence < 0.7."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = (
        '{"intent": "recall", "confidence": 0.48, '
        '"clarification_needed": true, '
        '"clarification_question": "Are you looking for a saved place called Fuji '
        'or a recommendation near there?"}'
    )
    mock_get_llm.return_value = mock_llm

    result = await classify_intent("fuji")

    assert isinstance(result, IntentClassification)
    assert result.clarification_needed is True
    assert result.clarification_question is not None
    assert len(result.clarification_question) > 0
