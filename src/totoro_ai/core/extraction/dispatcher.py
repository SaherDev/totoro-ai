"""Extraction dispatcher - routes raw input to appropriate extractor."""

from totoro_ai.core.extraction.input_parser import parse_input
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

        Parses mixed URL+text input to extract URL and supplementary context,
        then passes to extractors. Extractors decide if they support the input
        via supports() method. Each extractor receives both URL and supplementary
        text (where applicable).

        Args:
            raw_input: Raw user input (URL, text, or mixed format)

        Returns:
            ExtractionResult if an extractor succeeds, None if extraction failed

        Raises:
            UnsupportedInputError: If no extractor supports the input
        """
        # Parse input to extract URL and supplementary text
        parsed = parse_input(raw_input)

        # Route to first extractor that supports the input
        # Pass URL + context to extractors; they decide if they handle it
        input_to_test = parsed.url if parsed.url else parsed.supplementary_text

        for extractor in self._extractors:
            if extractor.supports(input_to_test):
                # Pass both URL and supplementary text; extractor decides what to use
                return await extractor.extract(input_to_test, parsed.supplementary_text)

        raise UnsupportedInputError(f"No extractor supports input: {raw_input[:50]}")
