"""Protocols for swappable extraction components."""

from typing import Protocol

from totoro_ai.core.extraction.result import ExtractionResult


class InputExtractor(Protocol):
    """Protocol for source-specific input extractors."""

    async def extract(self, raw_input: str) -> ExtractionResult | None:
        """
        Extract structured place data from raw input.

        Returns:
            ExtractionResult with extraction + source classification, or None on failure.
            The extractor owns source classification; service never re-derives it.
        """
        ...

    def supports(self, raw_input: str) -> bool:
        """Check if this extractor supports the given input."""
        ...
