"""Shared fixtures for agent-graph tests (feature 027 M3)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver


@pytest.fixture
def checkpointer() -> InMemorySaver:
    """In-memory checkpointer — structural tests do not hit Postgres."""
    return InMemorySaver()


@pytest.fixture
def mock_llm() -> MagicMock:
    """Fake chat model compatible with `agent_node`'s contract.

    - `.bind_tools(tools)` returns self (so the chain can still `.ainvoke`).
    - `.ainvoke(messages)` returns a preconfigured AIMessage (override in tests).

    Tests that need a specific response set `mock_llm.ainvoke.return_value`
    before invoking the graph/node.
    """
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm)

    async def _default_ainvoke(_messages: Any) -> AIMessage:
        return AIMessage(content="mock response")

    llm.ainvoke = MagicMock(side_effect=_default_ainvoke)
    return llm


@pytest.fixture
def no_tools() -> list[Any]:
    """Empty tool list — structural tests don't exercise real tools."""
    return []
