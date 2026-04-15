"""Pydantic schemas for the extract-place endpoint (ADR-017, ADR-018, ADR-054).

The response is a list of `ExtractPlaceItem`s. Each item carries either a
fully-populated `PlaceObject` (for `saved`/`duplicate`) or `None` (for
`pending`/`failed`), plus the extraction confidence if the cascade made it
to validation. No more top-level `provisional`/`pending_levels`/
`extraction_status` — each item is self-describing.
"""

from pydantic import BaseModel, Field

from totoro_ai.core.places import PlaceObject


class ExtractPlaceItem(BaseModel):
    """One row in the extract response.

    status values:
    - "saved"        — newly written to the permanent store; `place` is
                       set; confidence ≥ `confident_threshold`.
    - "needs_review" — newly written, but confidence falls in the
                       tentative band (between `save_threshold` and
                       `confident_threshold`); UI should prompt the user
                       to confirm or delete (ADR-057).
    - "duplicate"    — already existed; `place` is the existing row.
    - "pending"      — background enrichers are still running; caller
                       polls via `request_id`.
    - "failed"       — extraction did not yield a place (below
                       `save_threshold`, no candidates, validator found
                       nothing, …); `place` is None.
    """

    place: PlaceObject | None = None
    confidence: float | None = None
    status: str


class ExtractPlaceRequest(BaseModel):
    """Request body for extract-place endpoint."""

    user_id: str = Field(description="User ID (validated by NestJS)")
    raw_input: str = Field(description="TikTok URL or plain text")


class ExtractPlaceResponse(BaseModel):
    """Response body for extract-place endpoint."""

    results: list[ExtractPlaceItem]
    source_url: str | None = None
    request_id: str | None = None
