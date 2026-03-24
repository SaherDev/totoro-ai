"""Extraction dispatcher - routes raw input to appropriate extractor."""

from totoro_ai.core.extraction.protocols import InputExtractor
from totoro_ai.core.extraction.result import ExtractionResult


class UnsupportedInputError(Exception):
    """Raised when no extractor supports the given input."""

    pass


class ExtractionDispatcher:
    """Route raw input to the first extractor that supports it."""

    def __init__(self, extractors: list[InputExtractor]) -> None:
        """Initialize with list of extractors.

        Args:
            extractors: List of InputExtractor implementations, in priority order.
                        First extractor whose supports() returns True wins.
        """
        self._extractors = extractors

    async def dispatch(self, raw_input: str) -> ExtractionResult | None:
        """Dispatch raw input to first matching extractor.

        Args:
            raw_input: Raw user input (URL, text, etc.)

        Returns:
            ExtractionResult if an extractor succeeds, None if extraction failed

        Raises:
            UnsupportedInputError: If no extractor supports the input
        """
        for extractor in self._extractors:
            if extractor.supports(raw_input):
                return await extractor.extract(raw_input)

        raise UnsupportedInputError(f"No extractor supports input: {raw_input[:50]}")
