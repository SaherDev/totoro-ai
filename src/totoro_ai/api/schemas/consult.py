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


class PlacePhotos(BaseModel):
    """Photo URLs for a recommended place."""

    hero: str | None = None
    square: str | None = None


class PlaceResult(BaseModel):
    """A recommended place in the response."""

    place_name: str
    address: str
    reasoning: str
    source: str  # "saved" | "discovered"
    photos: PlacePhotos = PlacePhotos()


class ReasoningStep(BaseModel):
    """A step in the recommendation reasoning process."""

    step: str
    summary: str


class ConsultResponse(BaseModel):
    """Response body for POST /v1/consult."""

    primary: PlaceResult
    alternatives: list[PlaceResult]
    reasoning_steps: list[ReasoningStep]
