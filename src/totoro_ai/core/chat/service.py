"""ChatService — dispatch conversational requests to the correct pipeline."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from totoro_ai.api.schemas.chat import ChatRequest, ChatResponse
from totoro_ai.api.schemas.extract_place import ExtractPlaceResponse
from totoro_ai.core.chat.chat_assistant_service import ChatAssistantService
from totoro_ai.core.chat.router import classify_intent
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.core.consult.types import NoMatchesError
from totoro_ai.core.events.events import PersonalFactsExtracted
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.intent.intent_parser import IntentParser, ParsedIntent
from totoro_ai.core.recall.service import RecallService
from totoro_ai.core.recall.types import RecallFilters

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

    ConsultService is responsible for persisting recommendation records before returning.
    ChatService does not hold a RecommendationRepository reference.
    """

    def __init__(
        self,
        extraction_service: ExtractionService,
        consult_service: ConsultService,
        recall_service: RecallService,
        assistant_service: ChatAssistantService,
        intent_parser: IntentParser,
        event_dispatcher: EventDispatcherProtocol,
        memory_service: UserMemoryService,
    ) -> None:
        self._extraction = extraction_service
        self._consult = consult_service
        self._recall = recall_service
        self._assistant = assistant_service
        self._intent_parser = intent_parser
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
            classification = await classify_intent(
                request.message, user_id=request.user_id
            )
            logger.info(
                "Intent classification for user %s: intent=%s, facts=%s",
                request.user_id,
                classification.intent,
                [f.text for f in classification.personal_facts],
            )

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
            # M1 (feature 027): ExtractionService.run() now awaits the
            # pipeline inline. To preserve the HTTP fire-and-return
            # behavior, schedule it as a background task here and return
            # `pending` immediately with a request_id for polling.
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
                consult_result = await self._consult.consult(
                    request.user_id, request.message, request.location
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
            # ADR-057 follow-up: route recall through the intent parser so
            # meta-queries ("pull my saves") dispatch to filter-mode and
            # structured filters (subcategory, cuisine, city, ...) survive
            # as WHERE clauses instead of being lost to a raw-string vector
            # search. `enriched_query` is None for meta-queries, which the
            # recall service treats as filter-mode.
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

        # Unknown intent — treat as assistant fallback
        logger.warning("Unknown intent '%s' — falling back to assistant", intent)
        text = await self._assistant.run(request.message, request.user_id)
        return ChatResponse(
            type="assistant",
            message=text,
            data=None,
        )


def _filters_from_parsed(parsed: ParsedIntent) -> RecallFilters:
    """Project `ParsedIntent.place` onto `RecallFilters` for recall dispatch.

    `RecallFilters` mirrors `PlaceObject` (ADR-056 + feature 027 M4):
    top-level `place_type`/`subcategory`/`tags_include`/`source` plus a
    nested `attributes: PlaceAttributes`. This helper carries the parsed
    intent's attribute-level signals (cuisine, price_hint, location) into
    that nested container verbatim.
    """
    place = parsed.place
    return RecallFilters(
        place_type=place.place_type.value if place.place_type else None,
        subcategory=place.subcategory,
        tags_include=list(place.tags) if place.tags else None,
        attributes=place.attributes,
    )
