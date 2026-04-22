"""Tests for agent_node (feature 027 M3, FR-028).

M3 scope: structural only — node binds LLM, renders prompt, appends
response, increments steps_taken. Real LLM wiring lands in M6
(clarification 2026-04-21); tests here use a mocked LLM.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from totoro_ai.core.agent.graph import make_agent_node


def _base_state(**overrides: object) -> dict:
    state = {
        "messages": [HumanMessage(content="find me ramen")],
        "taste_profile_summary": "TASTE-SUBSTITUTED",
        "memory_summary": "MEMORY-SUBSTITUTED",
        "user_id": "u1",
        "location": None,
        "last_recall_results": None,
        "reasoning_steps": [],
        "steps_taken": 0,
        "error_count": 0,
    }
    state.update(overrides)  # type: ignore[arg-type]
    return state


@pytest.fixture
def captured_llm() -> MagicMock:
    """Mock LLM that records every call to ainvoke and returns a fixed AIMessage."""
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm)

    async def _ainvoke(messages: Any) -> AIMessage:
        return AIMessage(content="mocked agent response")

    llm.ainvoke = MagicMock(side_effect=_ainvoke)
    return llm


async def test_agent_node_binds_tools_via_injected_llm(
    captured_llm: MagicMock,
) -> None:
    tools: list[Any] = []
    make_agent_node(captured_llm, tools)
    captured_llm.bind_tools.assert_called_once_with(tools)


async def test_agent_node_renders_prompt_with_both_slots_substituted(
    captured_llm: MagicMock,
) -> None:
    node = make_agent_node(captured_llm, [])
    await node(_base_state())

    captured_llm.ainvoke.assert_called_once()
    sent_messages = captured_llm.ainvoke.call_args.args[0]
    system = sent_messages[0]
    assert isinstance(system, SystemMessage)
    # Both template slot literals must be GONE from the rendered prompt.
    assert "{taste_profile_summary}" not in system.content
    assert "{memory_summary}" not in system.content
    # And both substitution values must be PRESENT.
    assert "TASTE-SUBSTITUTED" in system.content
    assert "MEMORY-SUBSTITUTED" in system.content


async def test_agent_node_sends_system_plus_messages(captured_llm: MagicMock) -> None:
    node = make_agent_node(captured_llm, [])
    state = _base_state(messages=[HumanMessage(content="hello")])
    await node(state)

    sent_messages = captured_llm.ainvoke.call_args.args[0]
    assert len(sent_messages) == 2
    assert isinstance(sent_messages[0], SystemMessage)
    assert isinstance(sent_messages[1], HumanMessage)
    assert sent_messages[1].content == "hello"


async def test_agent_node_increments_steps_taken(captured_llm: MagicMock) -> None:
    node = make_agent_node(captured_llm, [])
    update = await node(_base_state(steps_taken=2))
    assert update["steps_taken"] == 3


async def test_agent_node_appends_ai_message(captured_llm: MagicMock) -> None:
    node = make_agent_node(captured_llm, [])
    update = await node(_base_state())
    msgs = update["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], AIMessage)
    assert msgs[0].content == "mocked agent response"


async def test_agent_node_empty_summaries_still_renders(
    captured_llm: MagicMock,
) -> None:
    """Slot substitution tolerates empty strings (used by routing/skeleton tests)."""
    node = make_agent_node(captured_llm, [])
    await node(_base_state(taste_profile_summary="", memory_summary=""))
    sent_messages = captured_llm.ainvoke.call_args.args[0]
    system = sent_messages[0]
    assert "{taste_profile_summary}" not in system.content
    assert "{memory_summary}" not in system.content
