"""Pydantic schemas for the extract-place endpoint (ADR-017, ADR-018)."""

from pydantic import BaseModel, Field


class SavedPlace(BaseModel):
    """A single place saved during extraction."""

    place_id: str
    place_name: str
    address: str | None
    city: str | None
    cuisine: str | None
    confidence: float
    resolved_by: str
    external_provider: str | None
    external_id: str | None


class ExtractPlaceRequest(BaseModel):
    """Request body for extract-place endpoint."""

    user_id: str = Field(description="User ID (validated by NestJS)")
    raw_input: str = Field(description="TikTok URL or plain text")


class ExtractPlaceResponse(BaseModel):
    """Response body for extract-place endpoint (Run 3 multi-place shape).

    extraction_status values:
    - "saved": one or more places written to DB; places is non-empty
    - "processing": no inline result; background enrichers running; provisional=True
    - "duplicate": all candidates already in DB; no new writes; places is empty
    """

    provisional: bool
    places: list[SavedPlace]
    pending_levels: list[str]
    extraction_status: str
    source_url: str | None
