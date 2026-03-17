from importlib.metadata import version as pkg_version

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from totoro_ai.api.routes.consult import router as consult_router
from totoro_ai.core.config import load_yaml_config
from totoro_ai.db.session import _get_session_factory

_app_config = load_yaml_config(".local.yaml")["app"]
_version = pkg_version("totoro-ai")

app = FastAPI(
    title=_app_config["name"],
    version=_version,
    description=_app_config["description"],
)

router = APIRouter(prefix=_app_config["api_prefix"])


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
        "name": _app_config["name"],
        "version": _version,
        "db": db_status,
    }


# Include routers
router.include_router(consult_router, prefix="")
app.include_router(router)
