"""Routes for POST /v1/consult endpoint with streaming and synchronous modes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from totoro_ai.api.schemas.consult import ConsultRequest
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.providers import get_llm

router = APIRouter()


def get_consult_service() -> ConsultService:
    """Dependency factory for ConsultService.

    Resolves the LLM client via provider abstraction (config-driven).
    Role 'orchestrator' maps to configured AI provider in config/models.yaml.

    Returns:
        ConsultService instance with orchestrator LLM client
    """
    return ConsultService(llm=get_llm("orchestrator"))


@router.post("/consult")
async def consult(
    body: ConsultRequest,
    raw_request: Request,
    service: ConsultService = Depends(get_consult_service),  # noqa: B008
) -> Response:
    """Handle POST /v1/consult with streaming and synchronous modes.

    Args:
        body: Request body with user_id, query, location, stream flag
        raw_request: FastAPI Request object for disconnect detection
        service: ConsultService dependency

    Returns:
        StreamingResponse if stream=true, JSONResponse if stream=false/absent
    """
    if body.stream:
        # Streaming mode: SSE (Server-Sent Events)
        return StreamingResponse(
            service.stream(body.user_id, body.query, raw_request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Synchronous mode: standard JSON response
    result = await service.consult(body.user_id, body.query, body.location)
    return JSONResponse(result.model_dump())
