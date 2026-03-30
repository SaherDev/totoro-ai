"""Routes for POST /v1/consult endpoint with streaming and synchronous modes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from totoro_ai.api.schemas.consult import ConsultRequest, ConsultResponse
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.providers import get_llm
from totoro_ai.providers.spell_correction import get_spell_corrector

router = APIRouter()


def get_consult_service() -> ConsultService:
    """Dependency factory for ConsultService.

    Resolves the LLM client via provider abstraction (config-driven).
    Role 'orchestrator' maps to configured AI provider in config/models.yaml.
    Spell corrector is resolved from provider abstraction (ADR-038).

    Returns:
        ConsultService instance with orchestrator LLM client and spell corrector
    """
    return ConsultService(
        llm=get_llm("orchestrator"), spell_corrector=get_spell_corrector()
    )


@router.post(
    "/consult",
    status_code=200,
    responses={
        200: {
            "description": "Synchronous recommendation response (stream=false)",
            "model": ConsultResponse,
        },
    },
)
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
