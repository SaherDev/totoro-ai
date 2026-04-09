"""Request/response schemas for the recall endpoint."""

from datetime import datetime

from pydantic import BaseModel, Field


class RecallRequest(BaseModel):
    """Recall request from NestJS."""

    query: str = Field(..., min_length=1, description="Natural language query")
    user_id: str = Field(..., description="User identifier (injected by NestJS)")


class RecallResult(BaseModel):
    """A single search result."""

    place_id: str
    place_name: str
    address: str
    cuisine: str | None = None
    price_range: str | None = None
    lat: float | None = None
    lng: float | None = None
    source_url: str | None = None
    saved_at: datetime = Field(description="When user saved this place")
    match_reason: str = Field(
        description="Why this result was returned: vector, text, or both"
    )


class RecallResponse(BaseModel):
    """Recall response to NestJS."""

    results: list[RecallResult]
    total: int = Field(description="Number of results returned (after limit)")
    empty_state: bool = Field(
        default=False, description="True only when user has zero saved places"
    )
