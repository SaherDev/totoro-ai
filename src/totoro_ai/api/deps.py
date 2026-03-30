"""FastAPI dependencies for route handlers (ADR-019)."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.core.config import AppConfig, get_config
from totoro_ai.core.extraction.dispatcher import ExtractionDispatcher
from totoro_ai.core.extraction.places_client import GooglePlacesClient
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.recall.service import RecallService
from totoro_ai.db.repositories import (
    SQLAlchemyEmbeddingRepository,
    SQLAlchemyPlaceRepository,
    SQLAlchemyRecallRepository,
)
from totoro_ai.db.session import get_session
from totoro_ai.providers import get_instructor_client
from totoro_ai.providers.embeddings import get_embedder
from totoro_ai.providers.spell_correction import get_spell_corrector


def build_dispatcher() -> ExtractionDispatcher:
    """Build ExtractionDispatcher with all configured extractors.

    Returns:
        ExtractionDispatcher with TikTok and plain text extractors in priority order.
    """
    from totoro_ai.core.extraction.extractors.plain_text import PlainTextExtractor
    from totoro_ai.core.extraction.extractors.tiktok import TikTokExtractor

    instructor_client = get_instructor_client("intent_parser")
    return ExtractionDispatcher(
        [TikTokExtractor(instructor_client), PlainTextExtractor(instructor_client)]
    )


async def get_extraction_service(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    config: AppConfig = Depends(get_config),  # noqa: B008
) -> ExtractionService:
    """FastAPI dependency providing a fully wired ExtractionService.

    Config and session are injected — override get_config in tests to avoid
    file I/O and control thresholds/weights without touching the filesystem.
    """
    return ExtractionService(
        dispatcher=build_dispatcher(),
        places_client=GooglePlacesClient(),
        place_repo=SQLAlchemyPlaceRepository(db_session),
        extraction_config=config.extraction,
        embedder=get_embedder(),
        embedding_repo=SQLAlchemyEmbeddingRepository(db_session),
        spell_corrector=get_spell_corrector(),
    )


async def get_recall_service(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    config: AppConfig = Depends(get_config),  # noqa: B008
) -> RecallService:
    """FastAPI dependency providing a fully wired RecallService."""
    return RecallService(
        embedder=get_embedder(),
        recall_repo=SQLAlchemyRecallRepository(db_session),
        config=config.recall,
        spell_corrector=get_spell_corrector(),
    )
