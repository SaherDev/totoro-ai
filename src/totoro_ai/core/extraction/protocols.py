"""Protocols for swappable extraction components."""

from typing import Protocol

from totoro_ai.core.extraction.result import ExtractionResult
from totoro_ai.core.extraction.types import ExtractionContext


class InputExtractor(Protocol):
    """Protocol for source-specific input extractors."""

    async def extract(
        self, raw_input: str, supplementary_text: str = ""
    ) -> ExtractionResult | None:
        """
        Extract structured place data from raw input.

        Args:
            raw_input: Primary input (URL or text)
            supplementary_text: Optional context (user description before/after URL)

        Returns:
            ExtractionResult with extraction + source classification,
            or None on failure. The extractor owns source classification;
            service never re-derives it.

        """
        ...

    def supports(self, raw_input: str) -> bool:
        """Check if this extractor supports the given input."""
        ...


class Enricher(Protocol):
    """Protocol for cascade enrichers (ADR-038).

    Enrichers populate ExtractionContext fields (caption, candidates, transcript).
    They always return None — results live in context, not in return values.
    External dependencies must be injected via constructor.
    """

    async def enrich(self, context: ExtractionContext) -> None: ...
