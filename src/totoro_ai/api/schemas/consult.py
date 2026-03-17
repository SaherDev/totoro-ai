"""Request and response schemas for POST /v1/consult endpoint."""

from pydantic import BaseModel


class Location(BaseModel):
    """User's geographic location."""

    lat: float
    lng: float


class ConsultRequest(BaseModel):
    """Request body for POST /v1/consult endpoint."""

    user_id: str
    query: str
    location: Location | None = None
    stream: bool = False


class PlaceResult(BaseModel):
    """A recommended place in the response."""

    place_name: str
    address: str
    reasoning: str
    source: str  # "saved" | "discovered"


class ReasoningStep(BaseModel):
    """A step in the recommendation reasoning process."""

    step: str
    summary: str


class SyncConsultResponse(BaseModel):
    """Response body for POST /v1/consult in synchronous mode."""

    primary: PlaceResult
    alternatives: list[PlaceResult]
    reasoning_steps: list[ReasoningStep]
