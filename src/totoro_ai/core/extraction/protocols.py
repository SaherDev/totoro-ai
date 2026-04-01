"""Protocols for the extraction pipeline."""

from typing import Protocol

from totoro_ai.core.extraction.models import ExtractionContext


class Enricher(Protocol):
    """Protocol for extraction enrichers (side-effect only).

    Enrichers mutate the ExtractionContext — populating caption, transcript,
    or appending to candidates — and always return None.
    """

    async def enrich(self, context: ExtractionContext) -> None: ...
