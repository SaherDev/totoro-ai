"""Unit tests for Plain Text extractor."""

from unittest.mock import AsyncMock

import pytest

from totoro_ai.core.extraction.confidence import ExtractionSource
from totoro_ai.core.extraction.extractors.plain_text import PlainTextExtractor
from totoro_ai.providers.llm import InstructorClient


@pytest.fixture
def mock_instructor_client() -> AsyncMock:
    """Fixture providing mock Instructor client."""
    return AsyncMock(spec=InstructorClient)


class TestPlainTextExtractor:
    """Test suite for PlainTextExtractor."""

    def test_supports_plain_text(self) -> None:
        """Test that supports() returns True for plain text."""
        extractor = PlainTextExtractor(AsyncMock(spec=InstructorClient))

        assert extractor.supports("Fuji Ramen on Main Street")
        assert extractor.supports("123 Main St, New York, NY 10001")
        assert extractor.supports("Best ramen restaurant in Shibuya")

    def test_rejects_http_urls(self) -> None:
        """Test that supports() returns False for HTTP/HTTPS URLs."""
        extractor = PlainTextExtractor(AsyncMock(spec=InstructorClient))

        assert not extractor.supports("https://tiktok.com/v/123")
        assert not extractor.supports("http://example.com")
        assert not extractor.supports("https://www.google.com")

    def test_accepts_non_http_schemes(self) -> None:
        """Test that supports() returns True for non-HTTP/HTTPS schemes (treated as plain text)."""
        extractor = PlainTextExtractor(AsyncMock(spec=InstructorClient))

        # ftp:// is not http/https so PlainTextExtractor accepts it as plain text
        assert extractor.supports("ftp://example.com")

    @pytest.mark.asyncio
    async def test_extract_successful(
        self, mock_instructor_client: AsyncMock
    ) -> None:
        """Test successful extraction from plain text."""
        from totoro_ai.api.schemas.extract_place import PlaceExtraction

        extractor = PlainTextExtractor(mock_instructor_client)

        mock_place = PlaceExtraction(
            place_name="Fuji Ramen",
            address="123 Main St, New York, NY",
            cuisine="ramen",
            price_range="mid",
        )
        mock_instructor_client.extract.return_value = mock_place

        result = await extractor.extract("Fuji Ramen at 123 Main Street, New York")

        assert result is not None
        assert result.source == ExtractionSource.PLAIN_TEXT
        assert result.source_url is None
        assert result.extraction.place_name == "Fuji Ramen"

    @pytest.mark.asyncio
    async def test_extract_handles_llm_failure(
        self, mock_instructor_client: AsyncMock
    ) -> None:
        """Test that None is returned on LLM extraction failure."""
        extractor = PlainTextExtractor(mock_instructor_client)

        mock_instructor_client.extract.side_effect = RuntimeError("LLM error")

        result = await extractor.extract("some text")

        assert result is None

    @pytest.mark.asyncio
    async def test_extract_handles_validation_failure(
        self, mock_instructor_client: AsyncMock
    ) -> None:
        """Test that None is returned on validation error."""
        extractor = PlainTextExtractor(mock_instructor_client)

        mock_instructor_client.extract.side_effect = ValueError("Validation error")

        result = await extractor.extract("some text")

        assert result is None
