"""Consult service for place recommendations with streaming and sync modes."""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import Request

from totoro_ai.api.schemas.consult import (
    Location,
    PlaceResult,
    ReasoningStep,
    SyncConsultResponse,
)
from totoro_ai.providers.llm import LLMClientProtocol

# System prompt for the AI provider (orchestrator role)
SYSTEM_PROMPT = (
    "You are Totoro, an AI place recommendation assistant. "
    "Answer the user's query helpfully and concisely."
)


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
    ) -> SyncConsultResponse:
        """Synchronous stub for place recommendation (Phase 1).

        Args:
            user_id: User identifier
            query: Natural language recommendation query
            location: Optional user location

        Returns:
            SyncConsultResponse with stub recommendation data
        """
        # Phase 1: Return stub response
        # Phase 4: Will call AI provider and parse real recommendations
        return SyncConsultResponse(
            primary=PlaceResult(
                place_name="Stub Place",
                address="123 Test St",
                reasoning="Stub response",
                source="saved",
            ),
            alternatives=[],
            reasoning_steps=[
                ReasoningStep(step="intent_parsing", summary="Parsing intent..."),
                ReasoningStep(step="ranking", summary="Ranking candidates..."),
            ],
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
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
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
