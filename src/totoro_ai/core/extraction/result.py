"""Extraction result model carrying both extraction data and source classification."""

from pydantic import BaseModel

from totoro_ai.api.schemas.extract_place import PlaceExtraction
from totoro_ai.core.extraction.confidence import ExtractionSource


class ExtractionResult(BaseModel):
    """Result from an extractor: structured place + source type."""

    extraction: PlaceExtraction
    source: ExtractionSource
    source_url: str | None = None
