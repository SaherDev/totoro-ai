"""Per-tool asyncio.wait_for guard (feature 028 M9)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from totoro_ai.core.agent.reasoning import ReasoningStep
from totoro_ai.core.config import get_config

logger = logging.getLogger(__name__)


async def with_timeout(
    tool_name: str,
    tool_call_id: str,
    state: dict[str, Any],
    body: Any,  # coroutine
) -> Command[Any]:
    """Enforce per-tool timeout from config.agent.tool_timeouts_seconds.

    On success, returns the Command from `body` unchanged.
    On asyncio.TimeoutError, returns a degraded Command that increments
    error_count and surfaces a user-visible tool.summary step.

    Args:
        tool_name: Logical tool name matching ToolTimeoutsConfig fields.
        tool_call_id: LangGraph tool call identifier for ToolMessage.
        state: Current AgentState snapshot (read for error_count/reasoning_steps).
        body: Coroutine producing the normal Command result.
    """
    timeout: int = getattr(get_config().agent.tool_timeouts_seconds, tool_name)
    try:
        return await asyncio.wait_for(body, timeout=float(timeout))
    except TimeoutError:
        logger.warning("tool %s timed out after %ss", tool_name, timeout)
        step = ReasoningStep(
            step="tool.summary",
            summary=f"{tool_name} timed out after {timeout}s — try again in a moment",
            source="tool",
            tool_name=tool_name,  # type: ignore[arg-type]
            visibility="user",
        )
        return Command(
            update={
                "error_count": state.get("error_count", 0) + 1,
                "reasoning_steps": (state.get("reasoning_steps") or []) + [step],
                "messages": [
                    ToolMessage(
                        content=(
                            f'{{"error": "timeout", "tool": "{tool_name}"}}'
                        ),
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )


__all__ = ["with_timeout"]
