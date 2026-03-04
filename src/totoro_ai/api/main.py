from importlib.metadata import version as pkg_version

from fastapi import APIRouter, FastAPI

from totoro_ai.core.config import load_yaml_config

_app_config = load_yaml_config("app.yaml")
_version = pkg_version("totoro-ai")

app = FastAPI(
    title=_app_config["name"],
    version=_version,
    description=_app_config["description"],
)

router = APIRouter(prefix=_app_config["api_prefix"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "name": _app_config["name"],
        "version": _version,
    }


app.include_router(router)
