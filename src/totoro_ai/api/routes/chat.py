"""POST /v1/chat and POST /v1/chat/stream — unified chat entry point (ADR-052)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage

from totoro_ai.api.deps import get_agent_graph, get_chat_service
from totoro_ai.api.schemas.chat import ChatRequest, ChatResponse
from totoro_ai.core.agent.invocation import build_turn_payload
from totoro_ai.core.agent.messages import extract_text_content
from totoro_ai.core.chat.service import ChatService

logger = logging.getLogger(__name__)

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


@router.post("/chat/stream", status_code=200)
async def chat_stream(
    body: ChatRequest,
    request: Request,
    service: ChatService = Depends(get_chat_service),  # noqa: B008
    agent_graph: Any = Depends(get_agent_graph),  # noqa: B008
) -> StreamingResponse:
    """SSE streaming chat endpoint — emits reasoning_step frames then final message.

    Requires agent path to be enabled and graph to be available.
    Returns 400 if agent is disabled or graph is unavailable.

    Frame format (text/event-stream):
      event: reasoning_step
      data: <ReasoningStep JSON>

      event: message
      data: {"content": "<final assistant text>"}

    Args:
        body: Chat request containing user_id, message, and optional location.
        request: FastAPI request (used for agent_graph via app.state).
        service: Injected ChatService (provides taste/memory helpers).
        agent_graph: Compiled LangGraph StateGraph from app.state.

    Returns:
        StreamingResponse with text/event-stream content type.
    """
    from fastapi.responses import JSONResponse

    if agent_graph is None or not service._config.agent.enabled:
        return JSONResponse(  # type: ignore[return-value]
            status_code=400,
            content={"detail": "Agent not enabled or graph unavailable"},
        )

    taste_summary = await service._compose_taste_summary(body.user_id)
    memory_summary = await service._compose_memory_summary(body.user_id)

    payload = build_turn_payload(
        message=body.message,
        user_id=body.user_id,
        taste_profile_summary=taste_summary,
        memory_summary=memory_summary,
        location=(body.location.model_dump() if body.location else None),
    )
    graph_config = {
        "configurable": {"thread_id": body.user_id},
        "metadata": {"user_id": body.user_id},
    }

    async def generate() -> AsyncGenerator[str, None]:
        final_message = ""
        tool_calls_used = 0
        try:
            async for event in agent_graph.astream_events(
                payload, config=graph_config, version="v2"
            ):
                event_type = event.get("event", "")
                if event_type == "on_custom_event":
                    data = event.get("data", {})
                    yield f"event: reasoning_step\ndata: {json.dumps(data)}\n\n"
                elif event_type == "on_chain_end":
                    output = event.get("data", {}).get("output", {})
                    if isinstance(output, dict):
                        messages = output.get("messages", [])
                        for m in reversed(messages):
                            if isinstance(m, AIMessage):
                                text = extract_text_content(m.content)
                                if text:
                                    final_message = text
                                    break
                        if "tool_calls_used" in output:
                            tool_calls_used = output["tool_calls_used"]
        except Exception as exc:
            logger.exception("chat_stream graph error: %s", exc)
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            return

        if final_message:
            yield f"event: message\ndata: {json.dumps({'content': final_message})}\n\n"
        done_payload = json.dumps({"tool_calls_used": tool_calls_used})
        yield f"event: done\ndata: {done_payload}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
