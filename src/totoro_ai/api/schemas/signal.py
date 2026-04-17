"""Request/response schemas for POST /v1/signal endpoint."""

from typing import Literal

from pydantic import BaseModel, Field


class SignalRequest(BaseModel):
    """Request body for POST /v1/signal."""

    signal_type: Literal["recommendation_accepted", "recommendation_rejected"] = Field(
        ..., description="Type of behavioral signal"
    )
    user_id: str = Field(..., description="User identifier (from Clerk auth)")
    recommendation_id: str = Field(
        ..., description="ID of the recommendation being responded to"
    )
    place_id: str = Field(
        ..., description="The place the user acted on"
    )


class SignalResponse(BaseModel):
    """Response body for POST /v1/signal."""

    status: str = Field(
        "accepted", description="Signal accepted and queued for processing"
    )
