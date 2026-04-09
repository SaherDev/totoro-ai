"""FastAPI dependencies for route handlers (ADR-019)."""

from __future__ import annotations

from fastapi import BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.core.config import AppConfig, ExtractionConfig, get_config, get_secrets
from totoro_ai.core.events.dispatcher import EventDispatcher
from totoro_ai.core.events.handlers import EventHandlers
from totoro_ai.core.extraction.enrichment_pipeline import EnrichmentPipeline
from totoro_ai.core.extraction.extraction_pipeline import ExtractionPipeline
from totoro_ai.core.extraction.persistence import ExtractionPersistenceService
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.core.intent.intent_parser import IntentParser
from totoro_ai.core.places import GooglePlacesClient
from totoro_ai.core.ranking.service import RankingService
from totoro_ai.core.recall.service import RecallService
from totoro_ai.core.taste.service import TasteModelService
from totoro_ai.db.repositories import (
    EmbeddingRepository,
    PlaceRepository,
    SQLAlchemyEmbeddingRepository,
    SQLAlchemyPlaceRepository,
    SQLAlchemyRecallRepository,
)
from totoro_ai.db.session import get_session
from totoro_ai.providers import get_instructor_client
from totoro_ai.providers.cache import CacheBackend
from totoro_ai.providers.embeddings import EmbedderProtocol, get_embedder
from totoro_ai.providers.groq_client import GroqWhisperClient
from totoro_ai.providers.llm import get_vision_extractor
from totoro_ai.providers.redis_cache import RedisCacheBackend


def get_cache_backend() -> CacheBackend:
    """FastAPI dependency providing CacheBackend (RedisCacheBackend by default)."""
    return RedisCacheBackend(url=get_secrets().redis.url)


def get_status_repo(
    cache: CacheBackend = Depends(get_cache_backend),  # noqa: B008
) -> ExtractionStatusRepository:
    """FastAPI dependency providing ExtractionStatusRepository."""
    return ExtractionStatusRepository(cache=cache)


def get_place_repo(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PlaceRepository:
    """FastAPI dependency providing PlaceRepository."""
    return SQLAlchemyPlaceRepository(db_session)


def get_embedding_repo(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> EmbeddingRepository:
    """FastAPI dependency providing EmbeddingRepository."""
    return SQLAlchemyEmbeddingRepository(db_session)


def get_extraction_config(
    config: AppConfig = Depends(get_config),  # noqa: B008
) -> ExtractionConfig:
    """FastAPI dependency providing ExtractionConfig."""
    return config.extraction


def get_embedder_dep() -> EmbedderProtocol:
    """FastAPI dependency providing EmbedderProtocol."""
    return get_embedder()


async def get_event_dispatcher(
    background_tasks: BackgroundTasks,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> EventDispatcher:
    """FastAPI dependency providing a fully wired EventDispatcher (ADR-043).

    ExtractionPersistenceService is constructed inline here (not via
    Depends(get_extraction_persistence)) to avoid a circular dependency:
    get_event_dispatcher <- get_extraction_persistence <- get_event_dispatcher.
    """
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
        "onboarding_signal", handlers.on_onboarding_signal  # type: ignore[arg-type]
    )

    # Register ExtractionPendingHandler (Run 3 — inline construction, no circular dep)
    from totoro_ai.core.extraction.enrichers.subtitle_check import SubtitleCheckEnricher
    from totoro_ai.core.extraction.enrichers.vision_frames import VisionFramesEnricher
    from totoro_ai.core.extraction.enrichers.whisper_audio import WhisperAudioEnricher
    from totoro_ai.core.extraction.handlers.extraction_pending import (
        ExtractionPendingHandler,
    )
    from totoro_ai.core.places import GooglePlacesClient
    from totoro_ai.core.extraction.validator import GooglePlacesValidator

    pending_persistence = ExtractionPersistenceService(
        place_repo=SQLAlchemyPlaceRepository(db_session),
        embedding_repo=SQLAlchemyEmbeddingRepository(db_session),
        embedder=get_embedder(),
        event_dispatcher=dispatcher,
    )
    pending_handler = ExtractionPendingHandler(
        background_enrichers=[
            SubtitleCheckEnricher(
                instructor_client=get_instructor_client("intent_parser"),
            ),
            WhisperAudioEnricher(
                groq_client=GroqWhisperClient(
                    api_key=get_secrets().providers.groq.api_key or ""
                ),
                instructor_client=get_instructor_client("intent_parser"),
            ),
            VisionFramesEnricher(
                vision_extractor=get_vision_extractor("vision_frames")
            ),
        ],
        validator=GooglePlacesValidator(
            places_client=GooglePlacesClient(),
            confidence_config=get_config().extraction.confidence,
        ),
        persistence=pending_persistence,
        status_repo=ExtractionStatusRepository(
            cache=RedisCacheBackend(url=get_secrets().redis.url)
        ),
    )
    dispatcher.register_handler(
        "extraction_pending", pending_handler.handle  # type: ignore[arg-type]
    )

    return dispatcher


def get_extraction_persistence(
    place_repo: PlaceRepository = Depends(get_place_repo),  # noqa: B008
    embedding_repo: EmbeddingRepository = Depends(get_embedding_repo),  # noqa: B008
    embedder: EmbedderProtocol = Depends(get_embedder_dep),  # noqa: B008
    event_dispatcher: EventDispatcher = Depends(get_event_dispatcher),  # noqa: B008
) -> ExtractionPersistenceService:
    """FastAPI dependency providing ExtractionPersistenceService."""
    return ExtractionPersistenceService(
        place_repo=place_repo,
        embedding_repo=embedding_repo,
        embedder=embedder,
        event_dispatcher=event_dispatcher,
    )


def _make_enrichment_pipeline() -> "EnrichmentPipeline":
    """Build EnrichmentPipeline with singleton circuit breaker instances."""
    from totoro_ai.core.extraction.circuit_breaker import (
        CircuitBreakerEnricher,
        ParallelEnricherGroup,
    )
    from totoro_ai.core.extraction.enrichers.llm_ner import LLMNEREnricher
    from totoro_ai.core.extraction.enrichers.tiktok_oembed import TikTokOEmbedEnricher
    from totoro_ai.core.extraction.enrichers.ytdlp_metadata import YtDlpMetadataEnricher
    from totoro_ai.core.extraction.enrichment_pipeline import EnrichmentPipeline

    return EnrichmentPipeline(
        [
            ParallelEnricherGroup(
                [
                    CircuitBreakerEnricher(TikTokOEmbedEnricher()),
                    CircuitBreakerEnricher(YtDlpMetadataEnricher()),
                ]
            ),
            LLMNEREnricher(instructor_client=get_instructor_client("intent_parser")),
        ]
    )


# Module-level singleton so circuit breaker state persists across requests.
_enrichment_pipeline: "EnrichmentPipeline | None" = None


def _get_enrichment_pipeline() -> "EnrichmentPipeline":
    global _enrichment_pipeline
    if _enrichment_pipeline is None:
        _enrichment_pipeline = _make_enrichment_pipeline()
    return _enrichment_pipeline


def get_extraction_pipeline(
    event_dispatcher: EventDispatcher = Depends(get_event_dispatcher),  # noqa: B008
    extraction_config: ExtractionConfig = Depends(get_extraction_config),  # noqa: B008
) -> ExtractionPipeline:
    """FastAPI dependency providing ExtractionPipeline with all enrichers wired."""
    from totoro_ai.core.extraction.enrichers.subtitle_check import SubtitleCheckEnricher
    from totoro_ai.core.extraction.enrichers.vision_frames import VisionFramesEnricher
    from totoro_ai.core.extraction.enrichers.whisper_audio import WhisperAudioEnricher
    from totoro_ai.core.places import GooglePlacesClient
    from totoro_ai.core.extraction.protocols import Enricher
    from totoro_ai.core.extraction.validator import GooglePlacesValidator

    enrichment = _get_enrichment_pipeline()
    validator = GooglePlacesValidator(
        places_client=GooglePlacesClient(),
        confidence_config=extraction_config.confidence,
    )
    background_enrichers: list[Enricher] = [
        SubtitleCheckEnricher(
            instructor_client=get_instructor_client("intent_parser"),
        ),
        WhisperAudioEnricher(
            groq_client=GroqWhisperClient(
                api_key=get_secrets().providers.groq.api_key or ""
            ),
            instructor_client=get_instructor_client("intent_parser"),
        ),
        VisionFramesEnricher(vision_extractor=get_vision_extractor()),
    ]
    return ExtractionPipeline(
        enrichment=enrichment,
        validator=validator,
        background_enrichers=background_enrichers,
        event_dispatcher=event_dispatcher,
        extraction_config=extraction_config,
    )


def get_extraction_service(
    pipeline: ExtractionPipeline = Depends(get_extraction_pipeline),  # noqa: B008
    persistence: ExtractionPersistenceService = Depends(  # noqa: B008
        get_extraction_persistence
    ),
) -> ExtractionService:
    """FastAPI dependency providing ExtractionService (2 deps replacing 7)."""
    return ExtractionService(pipeline=pipeline, persistence=persistence)


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


async def get_consult_service(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    config: AppConfig = Depends(get_config),  # noqa: B008
) -> ConsultService:
    """FastAPI dependency providing a fully wired ConsultService.

    Wires the 6-step pipeline dependencies: intent parser, recall service,
    places client, taste model service, and ranking service.
    """
    return ConsultService(
        intent_parser=IntentParser(),
        recall_service=RecallService(
            embedder=get_embedder(),
            recall_repo=SQLAlchemyRecallRepository(db_session),
            config=config.recall,
        ),
        places_client=GooglePlacesClient(),
        taste_service=TasteModelService(session=db_session),
        ranking_service=RankingService(),
    )
