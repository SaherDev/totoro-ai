"""Routes for POST /v1/consult endpoint."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from totoro_ai.api.deps import get_consult_service
from totoro_ai.api.schemas.consult import ConsultRequest, ConsultResponse
from totoro_ai.core.consult.service import ConsultService

router = APIRouter()


@router.post(
    "/consult",
    status_code=200,
    responses={
        200: {
            "description": "Synchronous recommendation response",
            "model": ConsultResponse,
        },
    },
)
async def consult(
    body: ConsultRequest,
    service: ConsultService = Depends(get_consult_service),  # noqa: B008
) -> JSONResponse:
    """Handle POST /v1/consult with 6-step pipeline.

    Args:
        body: Request body with user_id, query, location
        service: ConsultService dependency (5 wired services)

    Returns:
        JSONResponse with ConsultResponse payload
    """
    result = await service.consult(body.user_id, body.query, body.location)
    return JSONResponse(result.model_dump())
