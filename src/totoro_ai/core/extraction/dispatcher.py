"""Extraction dispatcher - routes raw input to appropriate extractor."""

from urllib.parse import urlparse

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

        Parses mixed URL+text input first, then routes to appropriate extractor:
        - If URL is TikTok: TikTokExtractor (with supplementary text as context)
        - If URL is other domain: Try each extractor
        - If plain text: PlainTextExtractor

        Args:
            raw_input: Raw user input (URL, text, or mixed)

        Returns:
            ExtractionResult if an extractor succeeds, None if extraction failed

        Raises:
            UnsupportedInputError: If no extractor supports the input
        """
        # Parse input to extract URL and supplementary text
        parsed = parse_input(raw_input)

        # Route to appropriate extractor
        if parsed.url:
            # Check if URL is TikTok
            try:
                parsed_url = urlparse(parsed.url)
                if "tiktok.com" in parsed_url.netloc:
                    # TikTok extractor handles URL + supplementary text
                    for extractor in self._extractors:
                        if extractor.supports(parsed.url):
                            # Pass both URL and context to TikTok extractor
                            return await extractor.extract(
                                parsed.url, parsed.supplementary_text
                            )
            except Exception:
                pass

            # For non-TikTok URLs, try extractors with just the URL
            for extractor in self._extractors:
                if extractor.supports(parsed.url):
                    return await extractor.extract(parsed.url)
        else:
            # Plain text: use supplementary_text with PlainTextExtractor
            for extractor in self._extractors:
                if extractor.supports(parsed.supplementary_text):
                    return await extractor.extract(parsed.supplementary_text)

        raise UnsupportedInputError(f"No extractor supports input: {raw_input[:50]}")
