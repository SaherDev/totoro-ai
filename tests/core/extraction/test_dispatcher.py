"""Unit tests for extraction dispatcher."""

import pytest

from totoro_ai.api.schemas.extract_place import PlaceExtraction
from totoro_ai.core.extraction.confidence import ExtractionSource
from totoro_ai.core.extraction.dispatcher import (
    ExtractionDispatcher,
    UnsupportedInputError,
)
from totoro_ai.core.extraction.protocols import InputExtractor
from totoro_ai.core.extraction.result import ExtractionResult


class MockExtractor(InputExtractor):
    """Mock extractor for testing."""

    def __init__(self, name: str, supports_pattern: str, source: ExtractionSource):
        self.name = name
        self.supports_pattern = supports_pattern
        self.source = source

    def supports(self, raw_input: str) -> bool:
        """Check if input contains support pattern."""
        return self.supports_pattern in raw_input

    async def extract(
        self, raw_input: str, supplementary_text: str = ""
    ) -> ExtractionResult | None:
        """Return mock extraction result."""
        return ExtractionResult(
            extraction=PlaceExtraction(
                place_name=f"Mock Place from {self.name}",
                address="123 Mock St",
                cuisine="test",
            ),
            source=self.source,
            source_url=raw_input if raw_input.startswith("http") else None,
        )


class TestExtractionDispatcher:
    """Test suite for ExtractionDispatcher."""

    async def test_dispatch_to_first_matching_extractor(self) -> None:
        """Test that dispatch() routes to the extractor that supports the input."""
        first = MockExtractor("first", "tiktok", ExtractionSource.CAPTION)
        second = MockExtractor("second", "plain", ExtractionSource.PLAIN_TEXT)

        dispatcher = ExtractionDispatcher([first, second])

        # "tiktok" matches first but not second
        result = await dispatcher.dispatch("https://tiktok.com/v/123")
        assert result is not None
        assert result.source == ExtractionSource.CAPTION

    async def test_dispatcher_raises_unsupported_input(self) -> None:
        """Test UnsupportedInputError when no extractor matches."""
        first = MockExtractor("first", "tiktok", ExtractionSource.CAPTION)
        second = MockExtractor("second", "plain", ExtractionSource.PLAIN_TEXT)

        dispatcher = ExtractionDispatcher([first, second])

        with pytest.raises(UnsupportedInputError):
            await dispatcher.dispatch("instagram.com/something")

    async def test_extractor_source_classification(self) -> None:
        """Test that ExtractionResult includes correct source."""
        extractor = MockExtractor("test", "test", ExtractionSource.CAPTION)
        dispatcher = ExtractionDispatcher([extractor])

        result = await dispatcher.dispatch("test input")
        assert result is not None
        assert result.source == ExtractionSource.CAPTION

    async def test_order_respected(self) -> None:
        """Test that extractors are checked in order."""
        # Both support "any", but first should win
        first = MockExtractor("first", "any", ExtractionSource.CAPTION)
        second = MockExtractor("second", "any", ExtractionSource.PLAIN_TEXT)

        dispatcher = ExtractionDispatcher([first, second])

        result = await dispatcher.dispatch("any input")
        assert result is not None
        # Should come from first extractor
        assert "first" in result.extraction.place_name.lower()
