from fastapi import APIRouter, FastAPI

app = FastAPI(title="Totoro AI", version="0.1.0")

v1_router = APIRouter(prefix="/v1")


@v1_router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(v1_router)
