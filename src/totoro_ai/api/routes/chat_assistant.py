"""Routes for POST /v1/chat-assistant endpoint."""

from fastapi import APIRouter, Depends

from totoro_ai.api.deps import get_chat_assistant_service
from totoro_ai.api.schemas.chat_assistant import ChatRequest, ChatResponse
from totoro_ai.core.chat.chat_assistant_service import ChatAssistantService

router = APIRouter()


@router.post(
    "/chat-assistant",
    status_code=200,
    response_model=ChatResponse,
)
async def chat_assistant(
    body: ChatRequest,
    service: ChatAssistantService = Depends(get_chat_assistant_service),  # noqa: B008
) -> ChatResponse:
    """Handle POST /v1/chat-assistant.

    Args:
        body: Request body with user_id and message.
        service: ChatAssistantService dependency.

    Returns:
        ChatResponse with the assistant's conversational answer.
    """
    response = await service.run(body.message, body.user_id)
    return ChatResponse(response=response)
