"""LangGraph agent skeleton: nodes, routing, factory (feature 027 M3, ADR-062).

Structural only — M3 does not wire the graph to `/v1/chat` (that is M6).
`agent_node` accepts an injected LLM; M3 tests drive it with a fake LLM
(per clarification). Real orchestrator wiring lands in M6's lazy graph
construction.

M9 additions: error wrapping in agent_node (increments error_count on
LLM failure) and debug diagnostic steps in fallback_node.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from totoro_ai.core.agent.messages import extract_text_content
from totoro_ai.core.agent.reasoning import ReasoningStep
from totoro_ai.core.agent.state import AgentState
from totoro_ai.core.config import get_config
from totoro_ai.providers.tracing import get_tracing_client

logger = logging.getLogger(__name__)

# Number of attempts for each LLM call in agent_node. Anthropic's API
# occasionally returns TLS handshake errors (SSLV3_ALERT_BAD_RECORD_MAC)
# or dropped connections — a small bounded retry absorbs these without
# surfacing to the user. Exponential backoff starting at 500ms.
_LLM_MAX_ATTEMPTS = 3
_LLM_BACKOFF_BASE_SECONDS = 0.5


async def _invoke_llm_with_retry(bound: Any, conversation: list[Any]) -> Any:
    """Call `bound.ainvoke(conversation)` with bounded retry.

    Retries any Exception up to `_LLM_MAX_ATTEMPTS` total attempts with
    exponential backoff. Re-raises the last exception on final failure.
    """
    last_exc: Exception | None = None
    for attempt in range(_LLM_MAX_ATTEMPTS):
        try:
            return await bound.ainvoke(conversation)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "LLM attempt %d/%d failed: %s",
                attempt + 1,
                _LLM_MAX_ATTEMPTS,
                exc,
            )
            if attempt < _LLM_MAX_ATTEMPTS - 1:
                await asyncio.sleep(_LLM_BACKOFF_BASE_SECONDS * (2**attempt))
    assert last_exc is not None
    raise last_exc


# Synthesized fallback decisions when AIMessage.content is empty but a
# tool was called — gives the user-visible `agent.tool_decision` step
# something concrete to render.
_TOOL_DECISION_FALLBACKS: dict[str, str] = {
    "recall": "recall — user referenced saved places",
    "save": "save — message contains URL or named place",
    "consult": "consult — recommendation request",
}
_DIRECT_RESPONSE_FALLBACK = "responding directly"

# Node names are re-used by tests asserting graph structure.
NODE_AGENT = "agent"
NODE_TOOLS = "tools"
NODE_FALLBACK = "fallback"

# Fallback message shown to the user when the graph terminates early.
_FALLBACK_MESSAGE = (
    "Something went wrong on my side — try again with a bit more detail?"
)


def _sanitize_orphaned_tool_calls(messages: list[Any]) -> tuple[list[Any], int]:
    """Inject placeholder ToolMessages for orphaned tool_use blocks.

    When a tool call is interrupted (timeout, server restart), the checkpointer
    stores an AIMessage with tool_calls but no subsequent ToolMessages. Sending
    that history to Anthropic causes a 400. We detect the condition and inject
    synthetic error ToolMessages so the conversation remains valid.

    Returns the sanitized message list and the count of injected placeholders.
    """
    result: list[Any] = []
    injected = 0
    for i, msg in enumerate(messages):
        result.append(msg)
        if not isinstance(msg, AIMessage):
            continue
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            continue
        expected_ids = {tc["id"] for tc in tool_calls if tc.get("id")}
        satisfied_ids: set[str] = set()
        j = i + 1
        while j < len(messages) and isinstance(messages[j], ToolMessage):
            tcid = getattr(messages[j], "tool_call_id", None)
            if tcid:
                satisfied_ids.add(tcid)
            j += 1
        for tc in tool_calls:
            if tc.get("id") in expected_ids - satisfied_ids:
                result.append(
                    ToolMessage(
                        content="Tool call did not complete — please continue.",
                        tool_call_id=tc["id"],
                    )
                )
                injected += 1
    return result, injected


def _render_system_prompt(state: AgentState) -> str:
    """Format the agent prompt with per-turn summaries substituted.

    Both template slots are validated at `_load_prompts()` boot time
    (FR-018a), so `.format(...)` on the loaded content is safe.
    """
    template = get_config().prompts["agent"].content
    return template.format(
        taste_profile_summary=state.get("taste_profile_summary") or "",
        memory_summary=state.get("memory_summary") or "",
    )


def make_agent_node(llm: Any, tools: list[Any]) -> Any:
    """Return an agent-node callable bound to `llm` and `tools`.

    The node renders the system prompt with per-turn summaries, calls
    `llm.bind_tools(tools).ainvoke(...)`, appends the response to
    `messages`, increments `steps_taken`, and emits one user-visible
    `agent.tool_decision` reasoning step per LLM call (feature 028 M5).

    The reasoning step's `summary` carries `AIMessage.content` truncated
    to 200 chars. When `content` is empty (tool-call-only response), a
    synthesized fallback keyed by the first tool-call name is used. A
    streaming caller (via `get_stream_writer()`) receives the full,
    untruncated text.
    """
    bound = llm.bind_tools(tools)

    async def agent_node(state: AgentState) -> dict[str, Any]:
        system = SystemMessage(content=_render_system_prompt(state))
        max_hist = get_config().agent.max_history_messages
        trimmed = state["messages"][-max_hist:]
        sanitized, dropped = _sanitize_orphaned_tool_calls(trimmed)
        if dropped:
            logger.warning(
                "Injected %d placeholder ToolMessage(s) for orphaned tool_use blocks",
                dropped,
            )
        conversation = [system, *sanitized]
        try:
            ai_msg = await _invoke_llm_with_retry(bound, conversation)
        except Exception as exc:
            logger.exception("agent_node failed after retries: %s", exc)
            tracer = get_tracing_client()
            span = tracer.generation(
                "agent_node",
                user_id=state.get("user_id"),
            )
            span.end(
                output={"error_type": "llm_retry_exhausted"},
                level="ERROR",
            )
            error_msg = AIMessage(
                content=(
                    "I hit a temporary connection issue talking to my language "
                    "model. Please try again in a moment."
                )
            )
            step = ReasoningStep(
                step="agent.tool_decision",
                summary=f"Connection error ({type(exc).__name__}) — please retry",
                source="agent",
                tool_name=None,
                visibility="user",
                duration_ms=0.0,
            )
            return {
                "messages": [error_msg],
                "error_count": state.get("error_count", 0) + 1,
                "steps_taken": state.get("steps_taken", 0) + 1,
                "reasoning_steps": (state.get("reasoning_steps") or []) + [step],
            }

        full_text = extract_text_content(getattr(ai_msg, "content", None)).strip()
        tool_calls = getattr(ai_msg, "tool_calls", None) or []
        first_tool_name = tool_calls[0].get("name") if tool_calls else None

        if not full_text:
            if first_tool_name is not None:
                summary_source = _TOOL_DECISION_FALLBACKS.get(
                    first_tool_name, _DIRECT_RESPONSE_FALLBACK
                )
            else:
                summary_source = _DIRECT_RESPONSE_FALLBACK
        else:
            summary_source = full_text

        try:
            writer = get_stream_writer()
        except RuntimeError:
            writer = None
        if writer is not None:
            writer({"step": "agent.tool_decision", "summary": summary_source})

        step = ReasoningStep(
            step="agent.tool_decision",
            summary=summary_source[:200],
            source="agent",
            tool_name=None,
            visibility="user",
            duration_ms=0.0,
        )
        existing_steps = state.get("reasoning_steps") or []
        return {
            "messages": [ai_msg],
            "steps_taken": state.get("steps_taken", 0) + 1,
            "reasoning_steps": existing_steps + [step],
        }

    return agent_node


def should_continue(state: AgentState) -> str:
    """Route from the agent node.

    Precedence (FR-026):
      error_count  >= max_errors  → "fallback"
      steps_taken  >= max_steps   → "fallback"
      last message has tool_calls → "tools"
      otherwise                    → "end"
    """
    cfg = get_config().agent
    if state.get("error_count", 0) >= cfg.max_errors:
        return NODE_FALLBACK
    if state.get("steps_taken", 0) >= cfg.max_steps:
        return NODE_FALLBACK

    messages = state.get("messages") or []
    if not messages:
        return "end"
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None)
    if tool_calls:
        return NODE_TOOLS
    return "end"


def fallback_node(state: AgentState) -> dict[str, Any]:
    """Compose a graceful terminal message + reasoning steps.

    Emits one user-visible ReasoningStep (FR-027) plus one debug diagnostic
    step (M9) when applicable (max_steps_detail / max_errors_detail).
    """
    cfg = get_config().agent
    steps_taken = state.get("steps_taken", 0)
    error_count = state.get("error_count", 0)

    debug_steps: list[ReasoningStep] = []
    if steps_taken >= cfg.max_steps:
        error_type = "max_steps"
        summary = (
            f"Got stuck after {cfg.max_steps} steps, something went wrong on my end"
        )
        debug_steps.append(
            ReasoningStep(
                step="max_steps_detail",
                summary=f"exceeded max_steps={cfg.max_steps}",
                source="fallback",
                tool_name=None,
                visibility="debug",
            )
        )
    elif error_count >= cfg.max_errors:
        error_type = "max_errors"
        summary = "Hit too many errors, try rephrasing or sharing more detail"
        debug_steps.append(
            ReasoningStep(
                step="max_errors_detail",
                summary=f"exceeded max_errors={cfg.max_errors}",
                source="fallback",
                tool_name=None,
                visibility="debug",
            )
        )
    else:
        error_type = "max_errors"
        summary = "Something went wrong on my end"

    tracer = get_tracing_client()
    span = tracer.generation("agent_fallback", user_id=state.get("user_id"))
    span.end(output={"error_type": error_type}, level="ERROR")

    user_step = ReasoningStep(
        step="fallback",
        summary=summary,
        source="fallback",
        tool_name=None,
        visibility="user",
    )
    existing_steps = state.get("reasoning_steps") or []
    return {
        "messages": [AIMessage(content=_FALLBACK_MESSAGE)],
        "reasoning_steps": existing_steps + debug_steps + [user_step],
    }


def build_graph(
    llm: Any,
    tools: list[Any],
    checkpointer: Any,
) -> Any:
    """Construct and compile the agent StateGraph (FR-025).

    Nodes: `agent`, `tools` (ToolNode), `fallback`.
    Conditional edges from `agent` via should_continue → {tools, fallback, end}.
    Direct edge tools → agent. Direct edge fallback → END.
    """
    graph: StateGraph = StateGraph(AgentState)
    graph.add_node(NODE_AGENT, make_agent_node(llm, tools))
    graph.add_node(NODE_TOOLS, ToolNode(tools))
    graph.add_node(NODE_FALLBACK, fallback_node)
    graph.set_entry_point(NODE_AGENT)
    graph.add_conditional_edges(
        NODE_AGENT,
        should_continue,
        {
            NODE_TOOLS: NODE_TOOLS,
            NODE_FALLBACK: NODE_FALLBACK,
            "end": END,
        },
    )
    graph.add_edge(NODE_TOOLS, NODE_AGENT)
    graph.add_edge(NODE_FALLBACK, END)
    return graph.compile(checkpointer=checkpointer)
