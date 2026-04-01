"""FastAPI dependencies for route handlers (ADR-019)."""

from fastapi import BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.core.config import AppConfig, get_config
from totoro_ai.core.events.dispatcher import EventDispatcher
from totoro_ai.core.events.handlers import EventHandlers
from totoro_ai.core.extraction.circuit_breaker import CircuitBreakerEnricher
from totoro_ai.core.extraction.enrichers.emoji_regex import EmojiRegexEnricher
from totoro_ai.core.extraction.enrichers.llm_ner import LLMNEREnricher
from totoro_ai.core.extraction.enrichers.parallel_group import ParallelEnricherGroup
from totoro_ai.core.extraction.enrichers.tiktok_oembed import TikTokOEmbedEnricher
from totoro_ai.core.extraction.enrichers.ytdlp_metadata import YtDlpMetadataEnricher
from totoro_ai.core.extraction.places_client import GooglePlacesClient
from totoro_ai.core.extraction.protocols import Enricher
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.extraction.validator import GooglePlacesValidator
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


def build_enricher_chain(config: AppConfig) -> list[Enricher]:
    """Build the Phase 1 enricher chain with circuit breakers.

    Returns enrichers in execution order:
    1. ParallelEnricherGroup(TikTok oEmbed + yt-dlp) — caption enrichers
    2. EmojiRegexEnricher — candidate enricher
    3. LLMNEREnricher — candidate enricher (no skip guard)
    """
    cb_config = config.extraction.circuit_breaker
    instructor_client = get_instructor_client("intent_parser")

    caption_enrichers = ParallelEnricherGroup(
        [
            CircuitBreakerEnricher(
                TikTokOEmbedEnricher(),
                failure_threshold=cb_config.failure_threshold,
                cooldown_seconds=cb_config.cooldown_seconds,
            ),
            CircuitBreakerEnricher(
                YtDlpMetadataEnricher(),
                failure_threshold=cb_config.failure_threshold,
                cooldown_seconds=cb_config.cooldown_seconds,
            ),
        ]
    )

    return [
        caption_enrichers,  # type: ignore[list-item]
        EmojiRegexEnricher(),  # type: ignore[list-item]
        LLMNEREnricher(instructor_client),  # type: ignore[list-item]
    ]


async def get_event_dispatcher(
    background_tasks: BackgroundTasks,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> EventDispatcher:
    """FastAPI dependency providing a fully wired EventDispatcher (ADR-043)."""
    taste_service = TasteModelService(session=db_session)
    handlers = EventHandlers(taste_service=taste_service, langfuse=None)

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
        "onboarding_signal",
        handlers.on_onboarding_signal,  # type: ignore[arg-type]
    )
    dispatcher.register_handler(
        "extraction_pending",
        handlers.on_extraction_pending,  # type: ignore[arg-type]
    )

    return dispatcher


async def get_extraction_service(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    config: AppConfig = Depends(get_config),  # noqa: B008
    event_dispatcher: EventDispatcher = Depends(get_event_dispatcher),  # noqa: B008
) -> ExtractionService:
    """FastAPI dependency providing a fully wired ExtractionService."""
    places_client = GooglePlacesClient()

    return ExtractionService(
        enricher_chain=build_enricher_chain(config),
        validator=GooglePlacesValidator(
            places_client=places_client,
            confidence_weights=config.extraction.confidence_weights,
        ),
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
