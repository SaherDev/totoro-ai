"""Tests for error_count failure budget in the agent graph (feature 028 M9)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from totoro_ai.core.agent.graph import NODE_FALLBACK, should_continue
from totoro_ai.core.agent.state import AgentState


async def test_should_continue_routes_to_fallback_on_max_errors() -> None:
    """should_continue returns NODE_FALLBACK when error_count >= max_errors."""
    from totoro_ai.core.config import get_config

    max_errors = get_config().agent.max_errors
    state: AgentState = {  # type: ignore[typeddict-item]
        "messages": [HumanMessage(content="hi"), AIMessage(content="ok")],
        "error_count": max_errors,
        "steps_taken": 0,
        "reasoning_steps": [],
        "last_recall_results": None,
        "user_id": "u1",
        "taste_profile_summary": "",
        "memory_summary": "",
        "location": None,
    }
    result = should_continue(state)
    assert result == NODE_FALLBACK


async def test_error_count_increments_on_agent_node_failure() -> None:
    """agent_node increments error_count when the LLM raises an exception."""
    from totoro_ai.core.agent.graph import make_agent_node

    failing_llm = MagicMock()
    failing_llm.bind_tools = MagicMock(return_value=failing_llm)

    async def _fail(_messages: Any) -> AIMessage:
        raise RuntimeError("LLM failed")

    failing_llm.ainvoke = MagicMock(side_effect=_fail)

    node = make_agent_node(failing_llm, [])
    state: AgentState = {  # type: ignore[typeddict-item]
        "messages": [HumanMessage(content="test")],
        "error_count": 0,
        "steps_taken": 0,
        "reasoning_steps": [],
        "last_recall_results": None,
        "user_id": "u1",
        "taste_profile_summary": "",
        "memory_summary": "",
        "location": None,
    }
    result = await node(state)
    assert result["error_count"] == 1
    assert result["steps_taken"] == 1


async def test_fallback_node_emits_user_visible_step() -> None:
    """fallback_node always emits a user-visible 'fallback' ReasoningStep."""
    from totoro_ai.core.agent.graph import fallback_node

    state: AgentState = {  # type: ignore[typeddict-item]
        "messages": [],
        "error_count": 0,
        "steps_taken": 0,
        "reasoning_steps": [],
        "last_recall_results": None,
        "user_id": "u1",
        "taste_profile_summary": "",
        "memory_summary": "",
        "location": None,
    }
    result = fallback_node(state)
    user_steps = [s for s in result["reasoning_steps"] if s.visibility == "user"]
    assert len(user_steps) == 1
    assert user_steps[0].step == "fallback"
