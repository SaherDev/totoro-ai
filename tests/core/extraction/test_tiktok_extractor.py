"""Unit tests for TikTok extractor."""

from unittest.mock import AsyncMock, patch

import pytest

from totoro_ai.core.extraction.confidence import ExtractionSource
from totoro_ai.core.extraction.extractors.tiktok import TikTokExtractor
from totoro_ai.providers.llm import InstructorClient


@pytest.fixture
def mock_instructor_client() -> AsyncMock:
    """Fixture providing mock Instructor client."""
    return AsyncMock(spec=InstructorClient)


class TestTikTokExtractor:
    """Test suite for TikTokExtractor."""

    def test_supports_tiktok_urls(self) -> None:
        """Test that supports() returns True for TikTok URLs."""
        extractor = TikTokExtractor(AsyncMock(spec=InstructorClient))

        assert extractor.supports("https://www.tiktok.com/@user/video/123")
        assert extractor.supports("https://tiktok.com/v/456")
        assert extractor.supports("http://tiktok.com/video/789")

    def test_rejects_non_tiktok_urls(self) -> None:
        """Test that supports() returns False for non-TikTok inputs."""
        extractor = TikTokExtractor(AsyncMock(spec=InstructorClient))

        assert not extractor.supports("https://instagram.com/p/123")
        assert not extractor.supports("https://youtube.com/watch?v=123")
        assert not extractor.supports("plain text input")
        assert not extractor.supports("123 Main St, New York, NY")

    @pytest.mark.asyncio
    async def test_extract_successful(
        self, mock_instructor_client: AsyncMock
    ) -> None:
        """Test successful extraction from TikTok caption."""
        from unittest.mock import MagicMock

        from totoro_ai.api.schemas.extract_place import PlaceExtraction

        extractor = TikTokExtractor(mock_instructor_client)

        # Mock oEmbed response
        mock_place = PlaceExtraction(
            place_name="Fuji Ramen",
            address="123 Main St, New York, NY",
            cuisine="ramen",
            price_range="low",
        )
        mock_instructor_client.extract.return_value = mock_place

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {"title": "Best ramen I ever had! Fuji Ramen"}

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            result = await extractor.extract("https://tiktok.com/v/123")

            assert result is not None
            assert result.source == ExtractionSource.CAPTION
            assert result.source_url == "https://tiktok.com/v/123"
            assert result.extraction.place_name == "Fuji Ramen"

    @pytest.mark.asyncio
    async def test_extract_handles_empty_caption(
        self, mock_instructor_client: AsyncMock
    ) -> None:
        """Test that None is returned when caption is empty."""
        from unittest.mock import MagicMock

        extractor = TikTokExtractor(mock_instructor_client)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {"title": None}

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            result = await extractor.extract("https://tiktok.com/v/123")

            assert result is None

    @pytest.mark.asyncio
    async def test_extract_handles_oEmbed_timeout(
        self, mock_instructor_client: AsyncMock
    ) -> None:
        """Test that timeout exceptions propagate."""
        import httpx

        extractor = TikTokExtractor(mock_instructor_client)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.TimeoutException("timeout")
            mock_client_class.return_value = mock_client

            with pytest.raises(RuntimeError, match="TikTok oEmbed timeout"):
                await extractor.extract("https://tiktok.com/v/123")
