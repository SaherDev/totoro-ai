"""POST /v1/chat route — unified chat entry point (ADR-052)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from totoro_ai.api.deps import get_chat_service
from totoro_ai.api.schemas.chat import ChatRequest, ChatResponse
from totoro_ai.core.chat.service import ChatService

router = APIRouter()


@router.post("/chat", status_code=200)
async def chat(
    body: ChatRequest,
    service: ChatService = Depends(get_chat_service),  # noqa: B008
) -> ChatResponse:
    """Unified chat endpoint — classify intent and dispatch to correct pipeline.

    Args:
        body: Chat request containing user_id, message, and optional location.
        service: Injected ChatService instance.

    Returns:
        ChatResponse with type, message, and optional data payload.
    """
    return await service.run(body)
