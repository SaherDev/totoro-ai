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
from totoro_ai.core.config import get_config
from totoro_ai.db.session import _get_session_factory

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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _validate_embedding_fts_alignment()
    # ADR-059: prompts are already loaded during get_config() at module scope
    logger.info("Loaded %d prompt templates", len(get_config().prompts))
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
