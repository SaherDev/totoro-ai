"""FastAPI dependencies for route handlers (ADR-019)."""

from fastapi import BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.core.config import AppConfig, get_config
from totoro_ai.core.events.dispatcher import EventDispatcher
from totoro_ai.core.events.handlers import EventHandlers
from totoro_ai.core.extraction.dispatcher import ExtractionDispatcher
from totoro_ai.core.extraction.places_client import GooglePlacesClient
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.recall.service import RecallService
from totoro_ai.core.taste.service import TasteModelService
from totoro_ai.db.repositories import (
    SQLAlchemyEmbeddingRepository,
    SQLAlchemyPlaceRepository,
    SQLAlchemyRecallRepository,
)
from totoro_ai.db.session import get_session
from totoro_ai.providers import get_instructor_client
from totoro_ai.providers.embeddings import get_embedder


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


async def get_event_dispatcher(
    background_tasks: BackgroundTasks,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> EventDispatcher:
    """FastAPI dependency providing a fully wired EventDispatcher (ADR-043).

    Per-request instance captures db_session and background_tasks.
    Handler registry is built here with all domain event handlers.

    Args:
        background_tasks: FastAPI BackgroundTasks for async handler execution
        db_session: Database session for handlers to use

    Returns:
        EventDispatcher with registered handlers
    """
    # Build TasteModelService dependency
    taste_service = TasteModelService(session=db_session)

    # Build EventHandlers
    handlers = EventHandlers(taste_service=taste_service, langfuse=None)

    # Create EventDispatcher with handler registry
    dispatcher = EventDispatcher(background_tasks=background_tasks)
    dispatcher.register_handler("place_saved", handlers.on_place_saved)  # type: ignore[arg-type]
    dispatcher.register_handler(
        "recommendation_accepted",
        handlers.on_recommendation_accepted,  # type: ignore[arg-type]
    )
    dispatcher.register_handler(
        "recommendation_rejected",
        handlers.on_recommendation_rejected,  # type: ignore[arg-type]
    )
    dispatcher.register_handler(
        "onboarding_signal", handlers.on_onboarding_signal  # type: ignore[arg-type]
    )

    return dispatcher


async def get_extraction_service(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    config: AppConfig = Depends(get_config),  # noqa: B008
    event_dispatcher: EventDispatcher = Depends(get_event_dispatcher),  # noqa: B008
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
        event_dispatcher=event_dispatcher,
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
    )
