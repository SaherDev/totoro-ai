"""Pydantic schemas for the extract-place endpoint (ADR-017, ADR-018)."""

from typing import Literal

from pydantic import BaseModel, Field


class PlaceExtraction(BaseModel):
    """Structured output from LLM extraction step. Not persisted directly."""

    place_name: str = Field(description="Name of the place")
    address: str = Field(description="Full address including city")
    cuisine: str | None = Field(
        default=None,
        description="Cuisine type e.g. ramen, italian",
    )
    price_range: Literal["low", "mid", "high"] | None = Field(
        default=None, description="low (<$15), mid ($15-40), high (>$40)"
    )


class ExtractPlaceRequest(BaseModel):
    """Request body for extract-place endpoint."""

    user_id: str = Field(description="User ID (validated by NestJS)")
    raw_input: str = Field(description="TikTok URL or plain text")


class ExtractPlaceResponse(BaseModel):
    """Response body for extract-place endpoint."""

    place_id: str | None = Field(
        description="UUID of saved place record; None when requires_confirmation=True"
    )
    place: PlaceExtraction = Field(description="Extracted and validated place data")
    confidence: float = Field(description="Confidence score (0.0-0.95)")
    requires_confirmation: bool = Field(
        description="True when 0.30 < confidence < 0.70; no DB write yet"
    )
    source_url: str | None = Field(
        description="Original TikTok URL; None for plain text"
    )
