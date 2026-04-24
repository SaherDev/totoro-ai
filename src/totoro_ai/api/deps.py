"""FastAPI dependencies for route handlers (ADR-019)."""

from __future__ import annotations

from typing import Any

from fastapi import BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.core.chat.service import ChatService
from totoro_ai.core.config import AppConfig, ExtractionConfig, get_config, get_env
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.core.events.dispatcher import EventDispatcher
from totoro_ai.core.events.handlers import EventHandlers
from totoro_ai.core.extraction.enrichment_pipeline import EnrichmentPipeline
from totoro_ai.core.extraction.extraction_pipeline import ExtractionPipeline
from totoro_ai.core.extraction.persistence import ExtractionPersistenceService
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository
from totoro_ai.core.memory.repository import SQLAlchemyUserMemoryRepository
from totoro_ai.core.memory.service import UserMemoryService
from totoro_ai.core.places import GooglePlacesClient, PlacesService
from totoro_ai.core.places.cache import PlacesCache
from totoro_ai.core.places.repository import PlacesRepository
from totoro_ai.core.recall.service import RecallService
from totoro_ai.core.signal.service import SignalService
from totoro_ai.core.taste.debounce import regen_debouncer
from totoro_ai.core.taste.service import TasteModelService
from totoro_ai.core.user.service import UserDeletionService
from totoro_ai.db.repositories import (
    EmbeddingRepository,
    SQLAlchemyEmbeddingRepository,
    SQLAlchemyRecallRepository,
)
from totoro_ai.db.repositories.recommendation_repository import (
    RecommendationRepository,
    SQLAlchemyRecommendationRepository,
)
from totoro_ai.db.session import _get_session_factory, get_session
from totoro_ai.providers import get_instructor_client
from totoro_ai.providers.cache import CacheBackend
from totoro_ai.providers.embeddings import EmbedderProtocol, get_embedder
from totoro_ai.providers.llm import get_transcription_client, get_vision_extractor
from totoro_ai.providers.redis_cache import RedisCacheBackend


def get_taste_service() -> TasteModelService:
    """FastAPI dependency providing TasteModelService.

    Uses session_factory so each repo method opens its own session.
    """
    return TasteModelService(session_factory=_get_session_factory())


def get_cache_backend() -> CacheBackend:
    """FastAPI dependency providing CacheBackend (RedisCacheBackend by default)."""
    return RedisCacheBackend(url=get_env().REDIS_URL)


def get_status_repo(
    cache: CacheBackend = Depends(get_cache_backend),  # noqa: B008
) -> ExtractionStatusRepository:
    """FastAPI dependency providing ExtractionStatusRepository."""
    return ExtractionStatusRepository(cache=cache)


def _build_places_cache() -> PlacesCache:
    """Construct a PlacesCache from the Redis URL in secrets.

    A fresh `redis.asyncio.Redis` client is built per call. The async client
    reuses its connection pool internally, so per-request construction is
    cheap and avoids the "client bound to the wrong event loop" pitfall.
    """
    from redis.asyncio import Redis

    redis_client = Redis.from_url(get_env().REDIS_URL, decode_responses=True)
    return PlacesCache(redis_client)


def get_places_service(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PlacesService:
    """FastAPI dependency providing `PlacesService` (ADR-054, feature 019).

    Wires the `PlacesRepository`, `PlacesCache`, and `GooglePlacesClient` so
    every caller consuming `PlacesService` sees a fully functional
    `enrich_batch` in both recall (`geo_only=True`) and consult modes.
    """
    return PlacesService(
        repo=PlacesRepository(db_session),
        cache=_build_places_cache(),
        client=GooglePlacesClient(),
    )


def get_embedding_repo(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> EmbeddingRepository:
    """FastAPI dependency providing EmbeddingRepository."""
    return SQLAlchemyEmbeddingRepository(db_session)


def get_user_memory_service() -> UserMemoryService:
    """FastAPI dependency providing UserMemoryService.

    CRITICAL (ADR-038): SQLAlchemyUserMemoryRepository is constructed ONLY here.
    Repo uses session_factory — each method opens its own session.
    """
    return UserMemoryService(
        repo=SQLAlchemyUserMemoryRepository(_get_session_factory())
    )


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

    Taste and memory services use session_factory — each repo method opens
    its own session, so background tasks don't depend on request session.
    """
    sf = _get_session_factory()
    taste_service = TasteModelService(session_factory=sf)
    memory_service = UserMemoryService(repo=SQLAlchemyUserMemoryRepository(sf))
    handlers = EventHandlers(
        taste_service=taste_service,
        memory_service=memory_service,
    )

    dispatcher = EventDispatcher(background_tasks=background_tasks)
    for event_type in (
        "place_saved",
        "recommendation_accepted",
        "recommendation_rejected",
        "onboarding_signal",
    ):
        dispatcher.register_handler(event_type, handlers.on_taste_signal)
    dispatcher.register_handler(
        "personal_facts_extracted",
        handlers.on_personal_facts_extracted,  # type: ignore[arg-type]
    )
    dispatcher.register_handler(
        "chip_confirmed",
        handlers.on_chip_confirmed,
    )

    return dispatcher


def get_places_cache_dep() -> PlacesCache:
    """FastAPI dependency providing `PlacesCache`.

    Extraction persistence takes this separately from `PlacesService` so
    it can write Tier 2 geo data directly after Google validation (ADR-057
    follow-up) — the service facade is the query path, the cache is the
    write path.
    """
    return _build_places_cache()


def get_extraction_persistence(
    places_service: PlacesService = Depends(get_places_service),  # noqa: B008
    places_cache: PlacesCache = Depends(get_places_cache_dep),  # noqa: B008
    embedding_repo: EmbeddingRepository = Depends(get_embedding_repo),  # noqa: B008
    embedder: EmbedderProtocol = Depends(get_embedder_dep),  # noqa: B008
    event_dispatcher: EventDispatcher = Depends(get_event_dispatcher),  # noqa: B008
) -> ExtractionPersistenceService:
    """FastAPI dependency providing ExtractionPersistenceService."""
    return ExtractionPersistenceService(
        places_service=places_service,
        places_cache=places_cache,
        embedding_repo=embedding_repo,
        embedder=embedder,
        event_dispatcher=event_dispatcher,
    )


def _make_enrichment_pipeline() -> EnrichmentPipeline:
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
            LLMNEREnricher(instructor_client=get_instructor_client("extractor")),
        ]
    )


# Module-level singleton so circuit breaker state persists across requests.
_enrichment_pipeline: EnrichmentPipeline | None = None


def _get_enrichment_pipeline() -> EnrichmentPipeline:
    global _enrichment_pipeline
    if _enrichment_pipeline is None:
        _enrichment_pipeline = _make_enrichment_pipeline()
    return _enrichment_pipeline


def get_extraction_pipeline(
    extraction_config: ExtractionConfig = Depends(get_extraction_config),  # noqa: B008
) -> ExtractionPipeline:
    """FastAPI dependency providing ExtractionPipeline with all enrichers wired."""
    from totoro_ai.core.extraction.enrichers.subtitle_check import SubtitleCheckEnricher
    from totoro_ai.core.extraction.enrichers.vision_frames import VisionFramesEnricher
    from totoro_ai.core.extraction.enrichers.whisper_audio import WhisperAudioEnricher
    from totoro_ai.core.extraction.protocols import Enricher
    from totoro_ai.core.extraction.validator import GooglePlacesValidator
    from totoro_ai.core.places import GooglePlacesClient

    enrichment = _get_enrichment_pipeline()
    validator = GooglePlacesValidator(
        places_client=GooglePlacesClient(),
        confidence_config=extraction_config.confidence,
    )
    background_enrichers: list[Enricher] = [
        SubtitleCheckEnricher(
            instructor_client=get_instructor_client("extractor"),
        ),
        WhisperAudioEnricher(
            transcription_client=get_transcription_client(),
            instructor_client=get_instructor_client("extractor"),
        ),
        VisionFramesEnricher(vision_extractor=get_vision_extractor()),
    ]
    return ExtractionPipeline(
        enrichment=enrichment,
        validator=validator,
        background_enrichers=background_enrichers,
        extraction_config=extraction_config,
    )


def get_extraction_service(
    pipeline: ExtractionPipeline = Depends(get_extraction_pipeline),  # noqa: B008
    persistence: ExtractionPersistenceService = Depends(  # noqa: B008
        get_extraction_persistence
    ),
    status_repo: ExtractionStatusRepository = Depends(get_status_repo),  # noqa: B008
) -> ExtractionService:
    """FastAPI dependency providing ExtractionService."""
    return ExtractionService(
        pipeline=pipeline, persistence=persistence, status_repo=status_repo
    )


async def get_recall_service(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    config: AppConfig = Depends(get_config),  # noqa: B008
    places_service: PlacesService = Depends(get_places_service),  # noqa: B008
) -> RecallService:
    """FastAPI dependency providing a fully wired RecallService."""
    return RecallService(
        embedder=get_embedder(),
        recall_repo=SQLAlchemyRecallRepository(db_session),
        config=config.recall,
        places_service=places_service,
    )


def get_recommendation_repo(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RecommendationRepository:
    """FastAPI dependency providing a fully wired RecommendationRepository (ADR-060)."""
    return SQLAlchemyRecommendationRepository(db_session)


def get_signal_service(
    event_dispatcher: EventDispatcher = Depends(get_event_dispatcher),  # noqa: B008
    taste_service: TasteModelService = Depends(get_taste_service),  # noqa: B008
) -> SignalService:
    """FastAPI dependency providing SignalService (ADR-060 + feature 023).

    SignalService owns the RecommendationRepository internally via
    session_factory. It also delegates chip_confirm handling to the
    TasteModelService (for chip read and merge persistence).
    """
    return SignalService(
        session_factory=_get_session_factory(),
        event_dispatcher=event_dispatcher,
        taste_service=taste_service,
    )


async def get_consult_service(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    recommendation_repo: RecommendationRepository = Depends(get_recommendation_repo),  # noqa: B008
) -> ConsultService:
    """FastAPI dependency providing a fully wired ConsultService (feature 028 M4).

    Wires the 4-phase pipeline dependencies: places client, places service,
    taste model service (active-tier chip filter only, ADR-061), and
    recommendation repository (ADR-060). IntentParser, RecallService, and
    UserMemoryService are no longer held by the consult service — the
    caller supplies pre-parsed `query`, pre-loaded `saved_places`, and an
    optional `preference_context`.
    """
    places_service = PlacesService(
        repo=PlacesRepository(db_session),
        cache=_build_places_cache(),
        client=GooglePlacesClient(),
    )
    return ConsultService(
        places_client=GooglePlacesClient(),
        places_service=places_service,
        taste_service=TasteModelService(session_factory=_get_session_factory()),
        recommendation_repo=recommendation_repo,
    )


def get_agent_checkpointer(request: Request) -> Any:
    """Return the process-scoped `AsyncPostgresSaver` warmed at startup.

    Populated by `api/main.py::_warm_agent_checkpointer`. Returns `None`
    when the lifespan hasn't run (test clients) or warmup failed.
    """
    return getattr(request.app.state, "agent_checkpointer", None)


def get_user_deletion_service(
    checkpointer: Any = Depends(get_agent_checkpointer),  # noqa: B008
) -> UserDeletionService:
    """FastAPI dependency providing UserDeletionService.

    Sweeps the five AI tables in one transaction (embeddings cascade
    from places via FK), then deletes the LangGraph checkpoint thread,
    then cancels any pending taste-regen task. See plan: hard-delete-only
    v1, sync sweep, 204 No Content.
    """
    return UserDeletionService(
        session_factory=_get_session_factory(),
        checkpointer=checkpointer,
        regen_debouncer=regen_debouncer,
    )


def get_agent_graph(
    recall_service: RecallService = Depends(get_recall_service),  # noqa: B008
    extraction_service: ExtractionService = Depends(get_extraction_service),  # noqa: B008
    consult_service: ConsultService = Depends(get_consult_service),  # noqa: B008
    checkpointer: Any = Depends(get_agent_checkpointer),  # noqa: B008
) -> Any:
    """Build the agent StateGraph per-request.

    Compiling per-request keeps tool-bound services request-scoped (fresh
    SQLAlchemy sessions, real EventDispatcher) while reusing the
    process-scoped checkpointer that owns its own psycopg pool.
    Compilation is cheap compared to the LLM call it shepherds, so the
    latency cost is negligible.
    """
    if checkpointer is None:
        return None
    from totoro_ai.core.agent.graph import build_graph
    from totoro_ai.core.agent.tools import build_tools
    from totoro_ai.providers.llm import get_langchain_chat_model

    tools = build_tools(recall_service, extraction_service, consult_service)
    llm = get_langchain_chat_model("orchestrator")
    return build_graph(llm, tools, checkpointer)


async def get_chat_service(
    extraction_service: ExtractionService = Depends(get_extraction_service),  # noqa: B008
    consult_service: ConsultService = Depends(get_consult_service),  # noqa: B008
    recall_service: RecallService = Depends(get_recall_service),  # noqa: B008
    event_dispatcher: EventDispatcher = Depends(get_event_dispatcher),  # noqa: B008
    memory_service: UserMemoryService = Depends(get_user_memory_service),  # noqa: B008
    taste_service: TasteModelService = Depends(get_taste_service),  # noqa: B008
    config: AppConfig = Depends(get_config),  # noqa: B008
    agent_graph: Any = Depends(get_agent_graph),  # noqa: B008
) -> ChatService:
    """FastAPI dependency providing a fully wired ChatService (ADR-019, ADR-052).

    Feature 028 M11 (ADR-065): legacy intent_parser and assistant_service
    removed — all traffic routed to the agent pipeline.
    """
    return ChatService(
        extraction_service=extraction_service,
        consult_service=consult_service,
        recall_service=recall_service,
        event_dispatcher=event_dispatcher,
        memory_service=memory_service,
        taste_service=taste_service,
        config=config,
        agent_graph=agent_graph,
    )
