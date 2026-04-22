"""LangGraph agent skeleton: nodes, routing, factory (feature 027 M3, ADR-062).

Structural only — M3 does not wire the graph to `/v1/chat` (that is M6).
`agent_node` accepts an injected LLM; M3 tests drive it with a fake LLM
(per clarification). Real orchestrator wiring lands in M6's lazy graph
construction.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from totoro_ai.core.agent.reasoning import ReasoningStep
from totoro_ai.core.agent.state import AgentState
from totoro_ai.core.config import get_config

# Node names are re-used by tests asserting graph structure.
NODE_AGENT = "agent"
NODE_TOOLS = "tools"
NODE_FALLBACK = "fallback"

# Fallback message shown to the user when the graph terminates early.
_FALLBACK_MESSAGE = (
    "Something went wrong on my side — try again with a bit more detail?"
)


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
    `messages`, and increments `steps_taken`. FR-028: LLM is injected;
    M3 tests use a fake.
    """
    bound = llm.bind_tools(tools)

    async def agent_node(state: AgentState) -> dict[str, Any]:
        system = SystemMessage(content=_render_system_prompt(state))
        conversation = [system, *state["messages"]]
        ai_msg = await bound.ainvoke(conversation)
        return {
            "messages": [ai_msg],
            "steps_taken": state.get("steps_taken", 0) + 1,
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
    """Compose a graceful terminal message + a user-visible fallback step.

    M3 emits exactly one user-visible ReasoningStep (FR-027, clarification
    2026-04-21). Debug diagnostic steps (`max_steps_detail` /
    `max_errors_detail`) are deferred to M9 and MUST NOT be emitted here.
    """
    cfg = get_config().agent
    steps_taken = state.get("steps_taken", 0)
    error_count = state.get("error_count", 0)
    if steps_taken >= cfg.max_steps:
        summary = (
            f"Got stuck after {cfg.max_steps} steps, something went wrong on my end"
        )
    elif error_count >= cfg.max_errors:
        summary = "Hit too many errors, try rephrasing or sharing more detail"
    else:
        summary = "Something went wrong on my end"

    step = ReasoningStep(
        step="fallback",
        summary=summary,
        source="fallback",
        tool_name=None,
        visibility="user",
    )
    existing_steps = state.get("reasoning_steps") or []
    return {
        "messages": [AIMessage(content=_FALLBACK_MESSAGE)],
        "reasoning_steps": existing_steps + [step],
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
