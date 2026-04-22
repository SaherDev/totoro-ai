"""ChatService — dispatch conversational requests to the correct pipeline.

Feature 028 M6 adds a flag fork: when `config.agent.enabled` is true,
`run()` routes to `_run_agent` which invokes the compiled LangGraph agent;
when false, the legacy `_run_legacy` path (classify_intent + dispatch)
runs unchanged. Flag defaults to off — no user-facing behavior change on
this feature's deploy.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from langchain_core.messages import AIMessage

from totoro_ai.api.schemas.chat import ChatRequest, ChatResponse
from totoro_ai.api.schemas.extract_place import ExtractPlaceResponse
from totoro_ai.core.agent.invocation import build_turn_payload
from totoro_ai.core.chat.chat_assistant_service import ChatAssistantService
from totoro_ai.core.chat.router import classify_intent
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.core.consult.types import NoMatchesError
from totoro_ai.core.events.events import PersonalFactsExtracted
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.intent.intent_parser import IntentParser, ParsedIntent
from totoro_ai.core.places.filters import ConsultFilters
from totoro_ai.core.recall.service import RecallService
from totoro_ai.core.recall.types import RecallFilters
from totoro_ai.core.taste.regen import format_summary_for_agent
from totoro_ai.core.taste.schemas import SummaryLine

if TYPE_CHECKING:
    from totoro_ai.core.config import AppConfig
    from totoro_ai.core.events.dispatcher import EventDispatcherProtocol
    from totoro_ai.core.memory.service import UserMemoryService
    from totoro_ai.core.taste.service import TasteModelService

logger = logging.getLogger(__name__)


class ChatService:
    """Unified chat entry point — classify intent and dispatch to the right pipeline."""

    def __init__(
        self,
        extraction_service: ExtractionService,
        consult_service: ConsultService,
        recall_service: RecallService,
        assistant_service: ChatAssistantService,
        intent_parser: IntentParser,
        event_dispatcher: EventDispatcherProtocol,
        memory_service: UserMemoryService,
        taste_service: TasteModelService,
        config: AppConfig,
        agent_graph: Any,
    ) -> None:
        self._extraction = extraction_service
        self._consult = consult_service
        self._recall = recall_service
        self._assistant = assistant_service
        self._intent_parser = intent_parser
        self._dispatcher = event_dispatcher
        self._memory = memory_service
        self._taste_service = taste_service
        self._config = config
        self._agent_graph = agent_graph

    async def run(self, request: ChatRequest) -> ChatResponse:
        """Fork on `config.agent.enabled`. Flag-off → legacy; flag-on → agent."""
        try:
            if self._config.agent.enabled and self._agent_graph is not None:
                return await self._run_agent(request)
            return await self._run_legacy(request)
        except Exception as exc:
            logger.exception("ChatService.run failed: %s", exc)
            return ChatResponse(
                type="error",
                message="Something went wrong, please try again.",
                data={"detail": str(exc)},
            )

    async def _run_legacy(self, request: ChatRequest) -> ChatResponse:
        """Classify intent and dispatch to the appropriate downstream service."""
        classification = await classify_intent(request.message, user_id=request.user_id)
        logger.info(
            "Intent classification for user %s: intent=%s, facts=%s",
            request.user_id,
            classification.intent,
            [f.text for f in classification.personal_facts],
        )

        await self._dispatcher.dispatch(
            PersonalFactsExtracted(
                user_id=request.user_id,
                personal_facts=classification.personal_facts,
            )
        )

        if classification.clarification_needed:
            question = (
                classification.clarification_question
                or "Could you clarify what you're looking for?"
            )
            return ChatResponse(
                type="clarification",
                message=question,
                data=None,
            )

        return await self._dispatch(request, classification.intent)

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
        final_state = await self._agent_graph.ainvoke(payload, config=graph_config)

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

    async def _dispatch(self, request: ChatRequest, intent: str) -> ChatResponse:
        """Route to the correct service based on classified intent."""
        if intent == "extract-place":
            request_id = uuid4().hex
            asyncio.create_task(
                self._extraction.run(
                    request.message, request.user_id, request_id=request_id
                )
            )
            pending = ExtractPlaceResponse(
                status="pending",
                results=[],
                raw_input=request.message,
                request_id=request_id,
            )
            return ChatResponse(
                type="extract-place",
                message="On it — extracting the place in the background. Check back in a moment.",
                data=pending.model_dump(mode="json"),
            )

        if intent == "consult":
            try:
                recall_response = await self._recall.run(
                    query=request.message,
                    user_id=request.user_id,
                    filters=None,
                )
                saved_places = [r.place for r in recall_response.results]
                consult_result = await self._consult.consult(
                    user_id=request.user_id,
                    query=request.message,
                    saved_places=saved_places,
                    filters=ConsultFilters(),
                    location=request.location,
                    preference_context=None,
                    signal_tier="active",
                )
            except NoMatchesError:
                return ChatResponse(
                    type="assistant",
                    message="I couldn't find a match for that. Try adding more places to your list, or give me a different area or vibe to work with.",
                    data=None,
                )
            top = consult_result.results[0].place.place_name
            return ChatResponse(
                type="consult",
                message=f"Here's my top pick: {top}",
                data=consult_result.model_dump(),
            )

        if intent == "recall":
            parsed = await self._intent_parser.parse(request.message)
            filters = _filters_from_parsed(parsed)
            recall_result = await self._recall.run(
                query=parsed.search.enriched_query,
                user_id=request.user_id,
                filters=filters,
            )
            count = len(recall_result.results)
            noun = "place" if count == 1 else "places"
            return ChatResponse(
                type="recall",
                message=f"Found {count} {noun} matching your search.",
                data=recall_result.model_dump(),
            )

        if intent == "assistant":
            text = await self._assistant.run(request.message, request.user_id)
            return ChatResponse(
                type="assistant",
                message=text,
                data=None,
            )

        logger.warning("Unknown intent '%s' — falling back to assistant", intent)
        text = await self._assistant.run(request.message, request.user_id)
        return ChatResponse(
            type="assistant",
            message=text,
            data=None,
        )


def _last_ai_message(messages: list[Any]) -> AIMessage | None:
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            return m
    return None


def _filters_from_parsed(parsed: ParsedIntent) -> RecallFilters:
    """Project `ParsedIntent.place` onto `RecallFilters` for recall dispatch."""
    place = parsed.place
    return RecallFilters(
        place_type=place.place_type if place.place_type else None,
        subcategory=place.subcategory,
        tags_include=list(place.tags) if place.tags else None,
        attributes=place.attributes,
    )
