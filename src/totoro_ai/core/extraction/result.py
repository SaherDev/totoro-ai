"""Extraction result model for validated place data."""

from pydantic import BaseModel

from totoro_ai.core.extraction.models import ExtractionLevel


class ExtractionResult(BaseModel):
    """Result from the extraction pipeline: validated place data + scoring."""

    place_name: str
    address: str | None = None
    city: str | None = None
    cuisine: str | None = None
    confidence: float
    resolved_by: ExtractionLevel
    corroborated: bool
    external_provider: str | None = None
    external_id: str | None = None
    source_url: str | None = None
