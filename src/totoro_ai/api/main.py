from importlib.metadata import version as pkg_version

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from totoro_ai.api.errors import register_error_handlers
from totoro_ai.api.routes.chat import router as chat_router
from totoro_ai.api.routes.feedback import router as feedback_router
from totoro_ai.core.config import get_config
from totoro_ai.db.session import _get_session_factory

_app_meta = get_config().app
_version = pkg_version("totoro-ai")

app = FastAPI(
    title=_app_meta.name,
    version=_version,
    description=_app_meta.description,
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


# Include routers (ADR-052: only /v1/chat handles conversational traffic)
router.include_router(chat_router, prefix="")
router.include_router(feedback_router, prefix="")
app.include_router(router)

# Register error handlers
register_error_handlers(app)
