"""ChatService — dispatch conversational requests to the correct pipeline."""

from __future__ import annotations

import logging

from typing import TYPE_CHECKING

from totoro_ai.api.schemas.chat import ChatRequest, ChatResponse
from totoro_ai.core.chat.chat_assistant_service import ChatAssistantService
from totoro_ai.core.chat.router import classify_intent
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.core.consult.types import NoMatchesError
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.events.events import PersonalFactsExtracted
from totoro_ai.core.recall.service import RecallService

if TYPE_CHECKING:
    from totoro_ai.core.events.dispatcher import EventDispatcherProtocol
    from totoro_ai.core.memory.service import UserMemoryService

logger = logging.getLogger(__name__)


class ChatService:
    """Unified chat entry point — classify intent and dispatch to the right pipeline.

    Constructor deps:
        extraction_service: Handles extract-place intent (TikTok / URLs / plain text).
        consult_service: Handles consult intent (place recommendations).
        recall_service: Handles recall intent (find saved places).
        assistant_service: Handles general food/dining questions.

    ConsultService is responsible for persisting consult log records before returning.
    ChatService does not hold a ConsultLogRepository reference.
    """

    def __init__(
        self,
        extraction_service: ExtractionService,
        consult_service: ConsultService,
        recall_service: RecallService,
        assistant_service: ChatAssistantService,
        event_dispatcher: EventDispatcherProtocol,
        memory_service: UserMemoryService,
    ) -> None:
        self._extraction = extraction_service
        self._consult = consult_service
        self._recall = recall_service
        self._assistant = assistant_service
        self._dispatcher = event_dispatcher
        self._memory = memory_service

    async def run(self, request: ChatRequest) -> ChatResponse:
        """Classify intent and dispatch to the appropriate downstream service.

        Steps:
        1. Classify intent with confidence gating.
        2. If clarification_needed → return clarification response.
        3. Dispatch by intent.
        4. Wrap result in ChatResponse.
        5. On any exception → return error response.

        Args:
            request: Incoming chat request.

        Returns:
            ChatResponse with type, message, and optional data payload.
        """
        try:
            classification = await classify_intent(request.message)

            # Fire PersonalFactsExtracted event to persist facts asynchronously
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

        except Exception as exc:
            logger.exception("ChatService.run failed: %s", exc)
            return ChatResponse(
                type="error",
                message="Something went wrong, please try again.",
                data={"detail": str(exc)},
            )

    async def _dispatch(self, request: ChatRequest, intent: str) -> ChatResponse:
        """Route to the correct service based on classified intent."""
        if intent == "extract-place":
            extract_result = await self._extraction.run(
                request.message, request.user_id
            )
            place_name = (
                extract_result.places[0].place_name
                if extract_result.places
                else "the place"
            )
            return ChatResponse(
                type="extract-place",
                message=f"Saved: {place_name}",
                data=extract_result.model_dump(),
            )

        if intent == "consult":
            try:
                consult_result = await self._consult.consult(
                    request.user_id, request.message, request.location
                )
            except NoMatchesError:
                return ChatResponse(
                    type="assistant",
                    message="I couldn't find a match for that. Try adding more places to your list, or give me a different area or vibe to work with.",
                    data=None,
                )
            return ChatResponse(
                type="consult",
                message=f"Here's my top pick: {consult_result.primary.place_name}",
                data=consult_result.model_dump(),
            )

        if intent == "recall":
            recall_result = await self._recall.run(request.message, request.user_id)
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

        # Unknown intent — treat as assistant fallback
        logger.warning("Unknown intent '%s' — falling back to assistant", intent)
        text = await self._assistant.run(request.message, request.user_id)
        return ChatResponse(
            type="assistant",
            message=text,
            data=None,
        )
