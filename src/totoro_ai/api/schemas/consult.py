"""Request and response schemas for POST /v1/consult endpoint.

The response carries the full `PlaceObject` per result (Tier 1/2/3 fields)
so the agent tool (see `agent-tool-design.md`) can project whichever
attributes it needs without a second fetch. The ranker's normalized score
is surfaced as `confidence` on each item.
"""

from pydantic import BaseModel

from totoro_ai.core.places.models import PlaceObject


class Location(BaseModel):
    """User's geographic location."""

    lat: float
    lng: float


class ConsultRequest(BaseModel):
    """Request body for POST /v1/consult endpoint."""

    user_id: str
    query: str
    location: Location | None = None


class ReasoningStep(BaseModel):
    """A step in the recommendation reasoning process."""

    step: str
    summary: str


class ConsultResult(BaseModel):
    """One recommendation in the consult response.

    `place` is the fully enriched `PlaceObject` (`enriched=True`, Tier 2
    geo and Tier 3 details populated). `confidence` is `ScoredPlace.score`
    — the ranker's weighted-and-clamped output, always in `[0, 1]`.
    `source` is `"saved"` when the row came from the user's recall set
    and `"discovered"` when it came from Google Places Nearby Search.
    """

    place: PlaceObject
    confidence: float
    source: str  # "saved" | "discovered"


class ConsultResponse(BaseModel):
    """Response body for POST /v1/consult.

    `results` is ordered by `confidence` descending (the ranker sorts
    internally) and capped at 3 entries. `reasoning_steps` is a flat
    trace of the six-step pipeline — useful for eval/debug, not required
    for the UI.
    """

    results: list[ConsultResult]
    reasoning_steps: list[ReasoningStep]
