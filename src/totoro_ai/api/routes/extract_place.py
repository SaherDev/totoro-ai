"""POST /v1/extract-place endpoint (ADR-034)."""

from fastapi import APIRouter, Depends

from totoro_ai.api.deps import get_extraction_service
from totoro_ai.api.schemas.extract_place import (
    ExtractPlaceRequest,
    ExtractPlaceResponse,
    ProvisionalResponse,
)
from totoro_ai.core.extraction.service import ExtractionService

router = APIRouter()


@router.post(
    "/extract-place",
    response_model=ExtractPlaceResponse | ProvisionalResponse,
)
async def extract_place(
    request: ExtractPlaceRequest,
    service: ExtractionService = Depends(get_extraction_service),  # noqa: B008
) -> ExtractPlaceResponse | ProvisionalResponse:
    """Extract and save (or confirm) places from raw input.

    Returns:
    - 200: Places saved/confirmed or provisional response for background processing
    - 400: Validation error (empty input)
    - 500: Internal error
    """
    return await service.run(request.raw_input, request.user_id)
