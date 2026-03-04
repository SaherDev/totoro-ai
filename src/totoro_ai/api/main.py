from pathlib import Path

import yaml
from fastapi import APIRouter, FastAPI

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "app.yaml"

with CONFIG_PATH.open() as f:
    _app_config: dict[str, str] = yaml.safe_load(f)

app = FastAPI(
    title=_app_config["name"],
    version=_app_config["version"],
    description=_app_config["description"],
)

v1_router = APIRouter(prefix="/v1")


@v1_router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "name": _app_config["name"],
        "version": _app_config["version"],
    }


app.include_router(v1_router)
