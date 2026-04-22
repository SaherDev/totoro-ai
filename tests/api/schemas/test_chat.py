"""Tests for ChatResponse schema (feature 028 M6 Literal tightening)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from totoro_ai.api.schemas.chat import ChatResponse


def test_chat_response_accepts_legacy_type_values() -> None:
    legacy = (
        "extract-place",
        "consult",
        "recall",
        "assistant",
        "clarification",
        "error",
    )
    for t in legacy:
        resp = ChatResponse(type=t, message="m")  # type: ignore[arg-type]
        assert resp.type == t


def test_chat_response_accepts_agent_type_value() -> None:
    resp = ChatResponse(type="agent", message="hello", data={"reasoning_steps": []})
    assert resp.type == "agent"
    assert resp.data == {"reasoning_steps": []}


def test_chat_response_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        ChatResponse(type="nonsense", message="m")  # type: ignore[arg-type]
