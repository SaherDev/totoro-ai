"""Consult service for place recommendations with streaming and sync modes."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import Request

from totoro_ai.api.schemas.consult import (
    ConsultResponse,
    Location,
    PlaceResult,
    ReasoningStep,
)
from totoro_ai.core.config import get_config
from totoro_ai.core.intent.intent_parser import IntentParser
from totoro_ai.providers import get_langfuse_client
from totoro_ai.providers.llm import LLMClientProtocol


class ConsultService:
    """Service for place recommendations with streaming and synchronous modes."""

    def __init__(self, llm: LLMClientProtocol) -> None:
        """Initialize the ConsultService with an LLM client.

        Args:
            llm: LLM client instance (resolved via provider abstraction)
        """
        self._llm = llm

    async def consult(
        self,
        user_id: str,
        query: str,
        location: Location | None = None,
    ) -> ConsultResponse:
        """Synchronous place recommendation with intent parsing and reasoning steps.

        Args:
            user_id: User identifier
            query: Natural language recommendation query
            location: Optional user location

        Returns:
            ConsultResponse with primary recommendation, alternatives, and
            reasoning steps
        """
        config = get_config()

        # Step 1: Parse intent from query
        parser = IntentParser()
        intent = await parser.parse(query)

        # Step 2: Build intent summary (non-null fields only)
        intent_parts = []
        if intent.cuisine:
            intent_parts.append(f"cuisine={intent.cuisine}")
        if intent.venue_type:
            intent_parts.append(f"venue_type={intent.venue_type}")
        if intent.occasion:
            intent_parts.append(f"occasion={intent.occasion}")
        if intent.price_range:
            intent_parts.append(f"price_range={intent.price_range}")
        intent_summary = (
            f"Parsed: {', '.join(intent_parts)}" if intent_parts else "Parsed query"
        )

        # Step 3: Helper to build step summaries with fallbacks
        def _build_summary(step_name: str) -> str:
            """Build step summary with intent-derived values and fallbacks."""
            place_type = intent.cuisine or intent.venue_type or "restaurants"
            location_context = "nearby"
            if location:
                location_context = f"near you (lat {location.lat}, lng {location.lng})"
            occasion = intent.occasion or "your criteria"
            radius = intent.radius / 1000 if intent.radius else 1.2  # convert m to km

            summaries = {
                "intent_parsing": intent_summary,
                "retrieval": (
                    f"Looking for {place_type} places you've saved near "
                    f"{location_context}"
                ),
                "discovery": (
                    f"Searching for {place_type} within {radius:.1f}km of your location"
                ),
                "validation": f"Checking which {place_type} are open now",
                "ranking": f"Comparing {place_type} for {occasion}",
                "completion": "Found your match",
            }
            return summaries.get(step_name, "Processing...")

        # Step 4: Build 6 reasoning steps
        reasoning_steps = [
            ReasoningStep(
                step="intent_parsing", summary=_build_summary("intent_parsing")
            ),
            ReasoningStep(step="retrieval", summary=_build_summary("retrieval")),
            ReasoningStep(step="discovery", summary=_build_summary("discovery")),
            ReasoningStep(step="validation", summary=_build_summary("validation")),
            ReasoningStep(step="ranking", summary=_build_summary("ranking")),
            ReasoningStep(step="completion", summary=_build_summary("completion")),
        ]

        # Step 5: Call orchestrator LLM to generate recommendation
        lf = get_langfuse_client()

        system_prompt = (
            "You are Totoro, an AI place recommendation assistant. "
            "Based on the user's query and parsed intent, recommend a primary place "
            "and 2 alternatives. Return ONLY a valid JSON object with this structure: "
            '{"primary": {"place_name": "...", "address": "...", "reasoning": "..."}, '
            '"alternatives": [{"place_name": "...", "address": "...", '
            '"reasoning": "..."}, {"place_name": "...", "address": "...", '
            '"reasoning": "..."}]} No markdown, no extra text, just JSON.'
        )
        enriched_query = (
            f"{query}\n\n"
            f"Parsed intent: {intent_summary}\n"
            "Recommend 1 primary place and 2 alternatives. "
            "Return valid JSON only."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": enriched_query},
        ]

        generation = None
        if lf:
            generation = lf.generation(
                name="recommendation_generation",
                input={"system": system_prompt, "user": enriched_query},
            )

        try:
            response_text = await self._llm.complete(messages)

            if generation:
                generation.end(output={"text": response_text})
        except Exception as e:
            if generation:
                generation.end(error=str(e))
            raise

        # Step 6: Parse LLM response as JSON
        try:
            response_json = json.loads(response_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM response is not valid JSON: {response_text}") from e

        # Validate structure
        if "primary" not in response_json or "alternatives" not in response_json:
            raise ValueError("LLM response missing 'primary' or 'alternatives' key")

        photo_url = config.consult.placeholder_photo_url
        max_alternatives = config.consult.max_alternatives

        # Step 7: Build response with primary from LLM
        primary_data = response_json["primary"]
        primary = PlaceResult(
            place_name=primary_data.get("place_name", "Restaurant"),
            address=primary_data.get("address", ""),
            reasoning=primary_data.get("reasoning", "Recommended for you"),
            source="discovered",
            photos=[photo_url],
        )

        # Build alternatives from LLM response
        alternatives = []
        alt_list = response_json.get("alternatives", [])
        for i in range(max_alternatives):
            alt_data = alt_list[i] if i < len(alt_list) else {}
            alternatives.append(
                PlaceResult(
                    place_name=alt_data.get("place_name", f"Alternative {i + 1}"),
                    address=alt_data.get("address", ""),
                    reasoning=alt_data.get("reasoning", "Also recommended"),
                    source="discovered",
                    photos=[photo_url],
                )
            )

        # Step 8: Return ConsultResponse
        return ConsultResponse(
            primary=primary,
            alternatives=alternatives,
            reasoning_steps=reasoning_steps,
        )

    async def stream(
        self,
        user_id: str,
        query: str,
        request: Request,
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from the AI provider in SSE format.

        Detects client disconnect and cleans up resources properly.

        Args:
            user_id: User identifier
            query: Natural language recommendation query
            request: FastAPI Request object for disconnect detection

        Yields:
            SSE events: {"token": "..."} per AI token, then {"done": true}
        """
        try:
            config = get_config()
            system_prompt = config.system_prompts.consult

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ]
            async for token in self._llm.stream(messages):
                # Check if client disconnected before emitting token
                if await request.is_disconnected():
                    break

                # Emit SSE event with token
                yield f"data: {json.dumps({'token': token})}\n\n"

            # Only emit done event if client is still connected
            if not await request.is_disconnected():
                yield f"data: {json.dumps({'done': True})}\n\n"

        except GeneratorExit:
            # Generator closed (e.g., client disconnect while iterating)
            pass
        finally:
            # Resource cleanup happens when async generator exits
            pass
