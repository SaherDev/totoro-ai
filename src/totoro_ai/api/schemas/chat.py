"""Request and response schemas for POST /v1/chat endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from totoro_ai.api.schemas.consult import Location


class ChatRequest(BaseModel):
    """Request body for POST /v1/chat endpoint."""

    user_id: str
    message: str
    location: Location | None = None


class ChatResponse(BaseModel):
    """Response body for POST /v1/chat endpoint.

    type: One of "extract-place", "consult", "recall", "assistant",
          "clarification", "error"
    message: Human-readable response text.
    data: Structured payload from downstream service; null for clarification/
          assistant/error.
    """

    type: str
    message: str
    data: dict[str, Any] | None = None
