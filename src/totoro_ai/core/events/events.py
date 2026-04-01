"""Domain event models for taste model updates and recommendation feedback"""

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    """Base class for all domain events"""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    user_id: str


class PlaceSaved(DomainEvent):
    """Event: User saved one or more places from a single extraction."""

    event_type: str = "place_saved"
    place_ids: list[str]
    place_metadata: list[dict[str, Any]] = Field(default_factory=list)


class ExtractionPending(DomainEvent):
    """Event: Background extraction dispatched (ADR-042/043)."""

    event_type: str = "extraction_pending"
    url: str | None = None
    supplementary_text: str = ""
    pending_levels: list[str] = Field(default_factory=list)


class RecommendationAccepted(DomainEvent):
    """Event: User accepted a recommendation"""

    event_type: str = "recommendation_accepted"
    recommendation_id: str
    place_id: str


class RecommendationRejected(DomainEvent):
    """Event: User rejected a recommendation"""

    event_type: str = "recommendation_rejected"
    recommendation_id: str
    place_id: str


class OnboardingSignal(DomainEvent):
    """Event: User confirmed or dismissed an onboarding taste chip"""

    event_type: str = "onboarding_signal"
    place_id: str
    confirmed: bool
