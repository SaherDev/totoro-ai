"""Request/response schemas for POST /v1/feedback endpoint"""

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    """Request schema for recommendation feedback"""

    user_id: str = Field(..., description="User identifier (injected from Clerk auth)")
    recommendation_id: str = Field(..., description="ID of the recommendation being responded to")
    place_id: str = Field(..., description="The place the user acted on (primary or alternative)")
    signal: Literal["accepted", "rejected"] = Field(..., description="Whether user accepted or rejected")


class FeedbackResponse(BaseModel):
    """Response schema for recommendation feedback"""

    status: str = Field("received", description="Feedback received and queued for processing")
