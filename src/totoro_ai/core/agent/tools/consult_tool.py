"""consult_tool — @tool wrapper around ConsultService (feature 028 M5)."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field

from totoro_ai.api.schemas.consult import ConsultResponse, Location
from totoro_ai.core.agent.state import AgentState
from totoro_ai.core.agent.tools._emit import append_summary, build_emit_closure
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.core.places.filters import ConsultFilters


class ConsultToolInput(BaseModel):
    """LLM-visible schema for the consult tool (SC-008/SC-009)."""

    query: str = Field(
        description=(
            "Retrieval phrase describing what to recommend, rewritten from "
            "the user's message. Examples: 'where should I eat tonight?' -> "
            "query='dinner restaurant'; 'I need a quiet place to work' -> "
            "query='quiet cafe laptop work'; 'something to do on a rainy "
            "afternoon' -> query='indoor activity'; 'a hotel near Shibuya' "
            "-> query='hotel Shibuya'."
        ),
    )
    filters: ConsultFilters = Field(
        description=(
            "Structural + discovery filters. Mirror PlaceObject plus "
            "radius_m and search_location_name."
        ),
    )
    preference_context: str | None = Field(
        default=None,
        description=(
            "One- or two-sentence summary composed from "
            "taste_profile_summary and memory_summary, limited to signals "
            "RELEVANT to this request. Example for a dinner request: "
            "'Prefers casual spots over formal. Wheelchair user. Avoids "
            "pork.' Example for a museum request: 'Likes contemporary art. "
            "Visits on weekdays. Wheelchair user.' Omit irrelevant signals."
        ),
    )


def _consult_summary(response: ConsultResponse) -> str:
    saved = sum(1 for r in response.results if r.source == "saved")
    discovered = sum(1 for r in response.results if r.source == "discovered")
    total = saved + discovered
    if total == 0:
        return "Nothing matched nearby"
    if saved == 0:
        return f"Ranked {discovered} nearby options"
    if discovered == 0:
        return f"Ranked {saved} from your saves"
    return f"Ranked {total} options ({saved} saved + {discovered} nearby)"


def build_consult_tool(service: ConsultService) -> BaseTool:
    """Return the @tool-decorated consult callable bound to `service`."""

    @tool("consult", args_schema=ConsultToolInput)
    async def consult_tool(
        query: str,
        filters: ConsultFilters,
        preference_context: str | None,
        state: Annotated[AgentState, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command[Any]:
        """Recommend a place.

        Merges the user's saved places (from the previous recall call,
        available automatically via agent state) with externally
        discovered candidates, deduplicates, and returns ranked results.

        Call recall FIRST in the same turn. If the user has no saved
        matches, call recall anyway — consult will work with the empty
        list and return discoveries only.
        """
        collected, emit = build_emit_closure("consult")
        saved_places = state.get("last_recall_results") or []
        raw_loc = state.get("location")
        loc: Location | None = (
            Location(lat=raw_loc["lat"], lng=raw_loc["lng"]) if raw_loc else None
        )
        response = await service.consult(
            user_id=state["user_id"],
            query=query,
            saved_places=saved_places,
            filters=filters,
            location=loc,
            preference_context=preference_context,
            signal_tier="active",
            emit=emit,
        )
        append_summary(collected, "consult", _consult_summary(response))
        update: dict[str, Any] = {
            "reasoning_steps": (state.get("reasoning_steps") or []) + collected,
            "messages": [
                ToolMessage(
                    content=response.model_dump_json(),
                    tool_call_id=tool_call_id,
                )
            ],
        }
        return Command(update=update)

    return consult_tool


__all__ = ["ConsultToolInput", "build_consult_tool"]
