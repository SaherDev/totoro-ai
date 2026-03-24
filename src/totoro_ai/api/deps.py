"""FastAPI dependencies for the extract-place endpoint (ADR-019)."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.core.extraction.dispatcher import ExtractionDispatcher
from totoro_ai.core.extraction.places_client import GooglePlacesClient
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.db.session import get_session
from totoro_ai.providers.llm import get_instructor_client


def build_dispatcher() -> ExtractionDispatcher:
    """Build ExtractionDispatcher with all configured extractors.

    Returns:
        ExtractionDispatcher with TikTok and plain text extractors

    Note:
        Extractors are initialized with Instructor client.
        Order matters: TikTok before plain text.
    """
    # Import here to avoid circular imports
    from totoro_ai.core.extraction.extractors.plain_text import PlainTextExtractor
    from totoro_ai.core.extraction.extractors.tiktok import TikTokExtractor

    instructor_client = get_instructor_client("intent_parser")

    tiktok = TikTokExtractor(instructor_client)
    plain_text = PlainTextExtractor(instructor_client)

    return ExtractionDispatcher([tiktok, plain_text])


async def get_extraction_service(
    db_session: AsyncSession = Depends(get_session),  # type: ignore[assignment]
) -> ExtractionService:
    """FastAPI dependency providing ExtractionService.

    Args:
        db_session: Database session from FastAPI dependency

    Returns:
        ExtractionService ready for use in route handlers
    """
    dispatcher = build_dispatcher()
    places_client = GooglePlacesClient()

    return ExtractionService(
        dispatcher=dispatcher,
        places_client=places_client,
        db_session_factory=lambda: db_session,
    )
