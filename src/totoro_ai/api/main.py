import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from totoro_ai.api.errors import register_error_handlers
from totoro_ai.api.routes.chat import router as chat_router
from totoro_ai.api.routes.extraction import router as extraction_router
from totoro_ai.api.routes.signal import router as signal_router
from totoro_ai.api.routes.user_context import router as user_context_router

# Agent graph construction (feature 028 M6) — imports are grouped so the
# lifespan hook can eagerly wire the compiled StateGraph once per process.
from totoro_ai.core.agent.checkpointer import build_checkpointer
from totoro_ai.core.agent.graph import build_graph
from totoro_ai.core.agent.tools import build_tools
from totoro_ai.core.config import get_config
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.core.places import GooglePlacesClient, PlacesService
from totoro_ai.core.places.cache import PlacesCache
from totoro_ai.core.places.repository import PlacesRepository
from totoro_ai.core.recall.service import RecallService
from totoro_ai.core.taste.service import TasteModelService
from totoro_ai.db.repositories import SQLAlchemyRecallRepository
from totoro_ai.db.session import _get_session_factory
from totoro_ai.providers.embeddings import get_embedder
from totoro_ai.providers.llm import get_langchain_chat_model

_log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
logging.root.setLevel(getattr(logging, _log_level, logging.WARNING))
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ADR-055: alignment between config.embeddings.description_fields and the
# search_vector generated column in migration a1b2c3d4e5f6. Any drift here
# means vector-similarity and FTS are searching different fields — retrieval
# quality degrades silently. The startup validator below logs CRITICAL when
# the two lists disagree.
# ---------------------------------------------------------------------------

_SEARCH_VECTOR_FIELDS = frozenset(
    {
        "place_name",
        "subcategory",
        "cuisine",
        "ambiance",
        "price_hint",
        "neighborhood",
        "city",
        "country",
    }
)


def _validate_embedding_fts_alignment() -> None:
    cfg_fields = frozenset(get_config().embeddings.description_fields)
    excluded = {"tags", "good_for", "dietary", "place_type"}
    mappable = cfg_fields - excluded
    missing = mappable - _SEARCH_VECTOR_FIELDS
    extra = _SEARCH_VECTOR_FIELDS - mappable
    if missing or extra:
        logger.critical(
            "embedding_fts_mismatch",
            extra={
                "in_config_not_in_search_vector": sorted(missing),
                "in_search_vector_not_in_config": sorted(extra),
            },
        )


_app_meta = get_config().app
try:
    _version = pkg_version("totoro-ai")
except PackageNotFoundError:
    _version = "0.1.0"


def _build_places_cache_for_lifespan() -> PlacesCache:
    """Construct a PlacesCache for agent-graph service wiring (feature 028 M6)."""
    from redis.asyncio import Redis

    from totoro_ai.core.config import get_secrets

    redis_client = Redis.from_url(get_secrets().REDIS_URL, decode_responses=True)
    return PlacesCache(redis_client)


class _NoopEventDispatcher:
    """No-op event dispatcher for the agent-graph wiring (feature 028 M6).

    The request-scoped `EventDispatcher` needs FastAPI's `BackgroundTasks`,
    which is not available in a lifespan hook. For the compiled-once-per-
    process agent graph we wire the extraction pipeline against a no-op
    dispatcher; downstream consequences on save-tool invocations:
    `PlaceSaved` events simply aren't dispatched on the agent path until
    a future feature reworks this. Safe under flag-off default.
    """

    async def dispatch(self, event: object) -> None:
        del event


async def _build_agent_graph(app: FastAPI) -> None:
    """Warm the compiled agent graph once per process (feature 028 M6).

    Builds recall / extraction / consult services with long-lived state
    (single session factory + no-op event dispatcher for the agent path),
    wraps them as tools, resolves the orchestrator LLM, and compiles the
    StateGraph. Stored on `app.state.agent_graph` for `get_agent_graph`
    to return.
    """
    from totoro_ai.api.deps import (
        _get_enrichment_pipeline,
        get_extraction_pipeline,
    )
    from totoro_ai.core.config import get_secrets
    from totoro_ai.core.extraction.persistence import ExtractionPersistenceService
    from totoro_ai.core.extraction.service import ExtractionService
    from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository
    from totoro_ai.db.repositories import SQLAlchemyEmbeddingRepository
    from totoro_ai.providers.redis_cache import RedisCacheBackend

    checkpointer = await build_checkpointer()
    session_factory = _get_session_factory()

    db_session = session_factory()
    places_service = PlacesService(
        repo=PlacesRepository(db_session),
        cache=_build_places_cache_for_lifespan(),
        client=GooglePlacesClient(),
    )
    recall = RecallService(
        embedder=get_embedder(),
        recall_repo=SQLAlchemyRecallRepository(db_session),
        config=get_config().recall,
        places_service=places_service,
    )

    _ = _get_enrichment_pipeline  # touched so module singletons initialize
    extraction_pipeline = get_extraction_pipeline(
        extraction_config=get_config().extraction,
    )
    cache_backend = RedisCacheBackend(url=get_secrets().REDIS_URL)
    status_repo = ExtractionStatusRepository(cache=cache_backend)
    extraction_persistence = ExtractionPersistenceService(
        places_service=places_service,
        places_cache=_build_places_cache_for_lifespan(),
        embedding_repo=SQLAlchemyEmbeddingRepository(db_session),
        embedder=get_embedder(),
        event_dispatcher=_NoopEventDispatcher(),
    )
    extraction = ExtractionService(
        pipeline=extraction_pipeline,
        persistence=extraction_persistence,
        status_repo=status_repo,
    )

    consult = ConsultService(
        places_client=GooglePlacesClient(),
        places_service=places_service,
        taste_service=TasteModelService(session_factory=session_factory),
    )

    tools = build_tools(recall, extraction, consult)
    llm = get_langchain_chat_model("orchestrator")
    app.state.agent_graph = build_graph(llm, tools, checkpointer)
    logger.info("Agent graph warmed (feature 028 M6)")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _validate_embedding_fts_alignment()
    # ADR-059: prompts are already loaded during get_config() at module scope
    logger.info("Loaded %d prompt templates", len(get_config().prompts))

    try:
        await _build_agent_graph(app)
    except Exception:
        logger.exception(
            "Agent graph construction failed; flag-off path still serves requests."
        )
        app.state.agent_graph = None

    yield
    # ADR-058: cancel in-flight taste regen debounce tasks on shutdown
    from totoro_ai.core.taste.debounce import regen_debouncer

    await regen_debouncer.cancel_all()


app = FastAPI(
    title=_app_meta.name,
    version=_version,
    description=_app_meta.description,
    lifespan=lifespan,
)

router = APIRouter(prefix=_app_meta.api_prefix)


@router.get("/health")
async def health() -> dict[str, str]:
    db_status = "disconnected"
    try:
        async with _get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        pass

    return {
        "status": "ok",
        "name": _app_meta.name,
        "version": _version,
        "db": db_status,
    }


# Include routers (ADR-052: /v1/chat handles conversational traffic)
router.include_router(chat_router, prefix="")
router.include_router(extraction_router, prefix="")
router.include_router(signal_router, prefix="")
router.include_router(user_context_router, prefix="")
app.include_router(router)

# Register error handlers
register_error_handlers(app)
