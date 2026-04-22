"""AgentState TypedDict for the LangGraph agent (feature 027 M3, ADR-062).

LangGraph's StateGraph requires TypedDict (not Pydantic). `messages` uses
the `add_messages` reducer so conversation history accumulates across
turns; every other field has plain-overwrite semantics (FR-021).

`last_recall_results` and `reasoning_steps` reset on every turn via
`build_turn_payload` in invocation.py — see that module for the single
construction site.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from totoro_ai.core.agent.reasoning import ReasoningStep
from totoro_ai.core.places.models import PlaceObject


class AgentState(TypedDict):
    """Per-turn state flowing through the LangGraph agent.

    Fields:
      messages            — conversation history; `add_messages` reducer appends.
      taste_profile_summary — behavior-derived preference bullets (per turn).
      memory_summary      — user-stated facts (per turn).
      user_id             — immutable per turn; used as the checkpointer thread_id.
      location            — {lat, lng} or None.
      last_recall_results — set by recall_tool (M5), read by consult_tool (M5);
                            reset to None on every new user message.
      reasoning_steps     — agent + tool trace; reset to [] on every new user
                            message; no reducer (plain overwrite, FR-021).
      steps_taken         — incremented by agent_node; bounds should_continue.
      error_count         — incremented by tool error handlers (M9); bounds
                            should_continue.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    taste_profile_summary: str
    memory_summary: str
    user_id: str
    location: dict[str, float] | None
    last_recall_results: list[PlaceObject] | None
    reasoning_steps: list[ReasoningStep]
    steps_taken: int
    error_count: int
