"""Pydantic schemas for the extract-place endpoint (ADR-017, ADR-018)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from totoro_ai.core.extraction.models import ExtractionLevel


class PlaceExtraction(BaseModel):
    """Structured output from LLM extraction step. Used by LLMNEREnricher."""

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


class ExtractedPlaceSchema(BaseModel):
    """Single validated place in the response."""

    place_id: str | None = Field(
        description="UUID of saved place record; None if requires_confirmation"
    )
    place_name: str
    address: str | None = None
    city: str | None = None
    cuisine: str | None = None
    confidence: float
    resolved_by: ExtractionLevel
    corroborated: bool = False
    external_provider: str | None = None
    external_id: str | None = None
    requires_confirmation: bool = Field(
        description="True when confidence < store_silently threshold"
    )

    @field_validator("confidence", mode="after")
    @classmethod
    def round_confidence(cls, v: float) -> float:
        return round(v, 2)


class ExtractPlaceResponse(BaseModel):
    """Response body for extract-place endpoint — multi-place support."""

    status: Literal["complete"] = "complete"
    places: list[ExtractedPlaceSchema]
    source_url: str | None = Field(description="Original URL; None for plain text")


class ProvisionalResponse(BaseModel):
    """Response when background processing is needed."""

    status: Literal["pending"] = "pending"
    message: str = "We're still working on identifying this place."
    pending_levels: list[ExtractionLevel] = Field(default_factory=list)
