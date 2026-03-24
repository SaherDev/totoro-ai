"""TikTok video caption extractor."""

from urllib.parse import urlparse

import httpx

from totoro_ai.api.schemas.extract_place import PlaceExtraction
from totoro_ai.core.extraction.confidence import ExtractionSource
from totoro_ai.core.extraction.result import ExtractionResult
from totoro_ai.providers.llm import InstructorClient


class TikTokExtractor:
    """Extract place from TikTok video caption (ADR-017, ADR-025)."""

    def __init__(self, instructor_client: InstructorClient) -> None:
        """Initialize with Instructor client for LLM extraction.

        Args:
            instructor_client: InstructorClient for structured extraction
        """
        self._instructor_client = instructor_client

    def supports(self, raw_input: str) -> bool:
        """Check if input is a TikTok URL.

        Args:
            raw_input: Raw user input (URL or text)

        Returns:
            True if input is a TikTok URL
        """
        try:
            parsed = urlparse(raw_input)
            return "tiktok.com" in parsed.netloc
        except Exception:
            return False

    async def extract(self, raw_input: str) -> ExtractionResult | None:
        """Extract place from TikTok video caption.

        Fetches video metadata via oEmbed API, extracts caption text,
        and runs LLM extraction on caption.

        Args:
            raw_input: TikTok URL

        Returns:
            ExtractionResult with extracted place data and source=CAPTION,
            or None if extraction failed

        Raises:
            RuntimeError: On oEmbed API failure
        """
        # Fetch caption from TikTok oEmbed API
        caption = await self._fetch_tiktok_caption(raw_input)
        if not caption:
            return None

        # Extract structured place from caption using LLM
        try:
            extraction = await self._instructor_client.extract(
                response_model=PlaceExtraction,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract restaurant details from the text. "
                            "Fill in as many fields as possible. "
                            "If information is missing, use null."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Extract restaurant information from this TikTok caption:"
                            f"\n\n{caption}"
                        ),
                    },
                ],
            )

            return ExtractionResult(
                extraction=extraction,
                source=ExtractionSource.CAPTION,
                source_url=raw_input,
            )
        except (RuntimeError, ValueError):
            # Extraction failed
            return None

    async def _fetch_tiktok_caption(self, url: str) -> str | None:
        """Fetch TikTok video metadata and extract caption.

        Uses public oEmbed endpoint with 3-second timeout.

        Args:
            url: TikTok video URL

        Returns:
            Caption text, or None if fetch failed

        Raises:
            RuntimeError: On HTTP/timeout errors
        """
        oembed_url = "https://www.tiktok.com/oembed"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    oembed_url,
                    params={"url": url},
                    timeout=3.0,
                )
                response.raise_for_status()
        except httpx.TimeoutException as e:
            raise RuntimeError(f"TikTok oEmbed timeout (3s): {e}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"TikTok oEmbed API error: {e}") from e

        data = response.json()
        return data.get("title") or None
