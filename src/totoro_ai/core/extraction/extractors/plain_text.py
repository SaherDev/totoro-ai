"""Plain text input extractor."""

from urllib.parse import urlparse

from totoro_ai.api.schemas.extract_place import PlaceExtraction
from totoro_ai.core.extraction.confidence import ExtractionSource
from totoro_ai.core.extraction.result import ExtractionResult
from totoro_ai.providers.llm import InstructorClient


class PlainTextExtractor:
    """Extract place from plain text description."""

    def __init__(self, instructor_client: InstructorClient) -> None:
        """Initialize with Instructor client for LLM extraction.

        Args:
            instructor_client: InstructorClient for structured extraction
        """
        self._instructor_client = instructor_client

    def supports(self, raw_input: str) -> bool:
        """Check if input is plain text (not a URL).

        Args:
            raw_input: Raw user input (URL or text)

        Returns:
            True if input is not an HTTP/HTTPS URL
        """
        try:
            parsed = urlparse(raw_input)
            # Plain text means no http/https scheme
            return parsed.scheme not in ("http", "https")
        except Exception:
            return True  # Assume plain text on parse error

    async def extract(self, raw_input: str) -> ExtractionResult | None:
        """Extract place from plain text using LLM.

        Args:
            raw_input: Plain text description of a place

        Returns:
            ExtractionResult with extracted place data and source=PLAIN_TEXT,
            or None if extraction failed
        """
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
                            "Extract restaurant information from this description:"
                            f"\n\n{raw_input}"
                        ),
                    },
                ],
            )

            return ExtractionResult(
                extraction=extraction,
                source=ExtractionSource.PLAIN_TEXT,
                source_url=None,
            )
        except (RuntimeError, ValueError):
            # Extraction failed
            return None
