"""Pydantic schemas for the extract-place endpoint (ADR-017, ADR-018)."""

from pydantic import BaseModel, Field


class SavedPlace(BaseModel):
    """A single place that passed through the extraction pipeline.

    extraction_status values:
    - "saved": written to DB; place_id is the new UUID
    - "duplicate": already in DB; place_id is the existing record's ID
    - "below_threshold": confidence below save_threshold; place_id is None
    - "failed_validation": Google Places returned no match; place_id is None
    """

    place_id: str | None
    place_name: str
    address: str | None
    city: str | None
    cuisine: str | None
    confidence: float
    resolved_by: str
    external_provider: str | None
    external_id: str | None
    extraction_status: str


class ExtractPlaceRequest(BaseModel):
    """Request body for extract-place endpoint."""

    user_id: str = Field(description="User ID (validated by NestJS)")
    raw_input: str = Field(description="TikTok URL or plain text")


class ExtractPlaceResponse(BaseModel):
    """Response body for extract-place endpoint (Run 3 multi-place shape).

    Top-level extraction_status values:
    - "saved": one or more places written to DB
    - "below_threshold": all candidates below confidence threshold; none saved
    - "duplicate": all candidates already in DB; no new writes
    - "processing": no inline result; background enrichers running; provisional=True

    Each entry in places carries its own extraction_status — see SavedPlace.
    """

    provisional: bool
    places: list[SavedPlace]
    pending_levels: list[str]
    extraction_status: str
    source_url: str | None
    request_id: str | None = None  # UUID4 for provisional responses; None otherwise
