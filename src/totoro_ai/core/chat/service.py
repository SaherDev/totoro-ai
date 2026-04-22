"""ChatService — dispatch conversational requests to the agent pipeline.

Feature 028 M11 (ADR-065): the legacy intent-router dispatch path
(classify_intent, ChatAssistantService, IntentParser) has been deleted.
`run()` always delegates to `_run_agent`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage
from langgraph.errors import GraphInterrupt

from totoro_ai.api.schemas.chat import ChatRequest, ChatResponse
from totoro_ai.core.agent.invocation import build_turn_payload
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.recall.service import RecallService
from totoro_ai.core.taste.regen import format_summary_for_agent
from totoro_ai.core.taste.schemas import SummaryLine

if TYPE_CHECKING:
    from totoro_ai.core.config import AppConfig
    from totoro_ai.core.events.dispatcher import EventDispatcherProtocol
    from totoro_ai.core.memory.service import UserMemoryService
    from totoro_ai.core.taste.service import TasteModelService

logger = logging.getLogger(__name__)


class ChatService:
    """Unified chat entry point — delegates all traffic to the agent pipeline."""

    def __init__(
        self,
        extraction_service: ExtractionService,
        consult_service: ConsultService,
        recall_service: RecallService,
        event_dispatcher: EventDispatcherProtocol,
        memory_service: UserMemoryService,
        taste_service: TasteModelService,
        config: AppConfig,
        agent_graph: Any,
    ) -> None:
        self._extraction = extraction_service
        self._consult = consult_service
        self._recall = recall_service
        self._dispatcher = event_dispatcher
        self._memory = memory_service
        self._taste_service = taste_service
        self._config = config
        self._agent_graph = agent_graph

    async def run(self, request: ChatRequest) -> ChatResponse:
        """Delegate to `_run_agent` — the only dispatch path (ADR-065)."""
        try:
            return await self._run_agent(request)
        except Exception as exc:
            logger.exception("ChatService.run failed: %s", exc)
            return ChatResponse(
                type="error",
                message="Something went wrong, please try again.",
                data={"detail": str(exc)},
            )

    async def _run_agent(self, request: ChatRequest) -> ChatResponse:
        """Invoke the compiled agent graph and map its final state to ChatResponse."""
        taste_summary = await self._compose_taste_summary(request.user_id)
        memory_summary = await self._compose_memory_summary(request.user_id)

        payload = build_turn_payload(
            message=request.message,
            user_id=request.user_id,
            taste_profile_summary=taste_summary,
            memory_summary=memory_summary,
            location=(request.location.model_dump() if request.location else None),
        )

        graph_config = {
            "configurable": {"thread_id": request.user_id},
            "metadata": {"user_id": request.user_id},
        }
        try:
            final_state = await self._agent_graph.ainvoke(payload, config=graph_config)
        except GraphInterrupt as interrupt:
            # LangGraph wraps NodeInterrupt payload as:
            #   interrupt.args[0] == [Interrupt(value=<payload>, ...)]
            # Direct GraphInterrupt construction passes args[0] as a plain dict.
            raw = interrupt.args[0] if interrupt.args else {}
            if isinstance(raw, list) and raw and hasattr(raw[0], "value"):
                interrupt_val: dict[str, Any] = raw[0].value
            elif isinstance(raw, dict):
                interrupt_val = raw
            else:
                interrupt_val = {}
            candidates = (
                interrupt_val.get("candidates", [])
                if isinstance(interrupt_val, dict)
                else []
            )
            name = (
                candidates[0].get("place", {}).get("place_name", "this place")
                if candidates
                else "this place"
            )
            return ChatResponse(
                type="clarification",
                message=f"Low confidence on {name} — is this the place you meant?",
                data={"interrupt": interrupt_val},
            )

        ai_message = _last_ai_message(final_state.get("messages", []))
        user_steps = [
            s for s in final_state.get("reasoning_steps", []) if s.visibility == "user"
        ]

        return ChatResponse(
            type="agent",
            message=ai_message.content if ai_message else "",
            data={"reasoning_steps": [s.model_dump(mode="json") for s in user_steps]},
        )

    async def _compose_taste_summary(self, user_id: str) -> str:
        profile = await self._taste_service.get_taste_profile(user_id)
        if profile is None or not profile.taste_profile_summary:
            return ""
        lines = [
            SummaryLine.model_validate(item) if isinstance(item, dict) else item
            for item in profile.taste_profile_summary
        ]
        return format_summary_for_agent(lines)

    async def _compose_memory_summary(self, user_id: str) -> str:
        memory_list = await self._memory.load_memories(user_id)
        if not memory_list:
            return ""
        return "\n".join(memory_list)

def _last_ai_message(messages: list[Any]) -> AIMessage | None:
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            return m
    return None
