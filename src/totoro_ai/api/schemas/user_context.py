"""Request/response schemas for GET /v1/user/context endpoint."""

from pydantic import BaseModel, Field


class ChipResponse(BaseModel):
    """Taste chip for display in the product UI."""

    label: str = Field(..., description="Short display label (e.g. 'Japanese')")
    source_field: str = Field(..., description="Field the chip was derived from")
    source_value: str = Field(..., description="Value of source_field")
    signal_count: int = Field(..., description="Number of signals for this chip")


class UserContextResponse(BaseModel):
    """Response body for GET /v1/user/context."""

    saved_places_count: int = Field(
        ..., description="Total number of places the user has saved"
    )
    chips: list[ChipResponse] = Field(
        default_factory=list, description="Precomputed taste chips"
    )
