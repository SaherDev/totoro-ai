"""POST /v1/extract-place endpoint (ADR-034)."""

from fastapi import APIRouter, Depends

from totoro_ai.api.deps import get_extraction_service
from totoro_ai.api.schemas.extract_place import (
    ExtractPlaceRequest,
    ExtractPlaceResponse,
)
from totoro_ai.core.extraction.service import ExtractionService

router = APIRouter()


@router.post("/extract-place", response_model=ExtractPlaceResponse)
async def extract_place(
    request: ExtractPlaceRequest,
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractPlaceResponse:
    """Extract and save (or confirm) a place from raw input.

    Request body:
    - user_id: User identifier
    - raw_input: TikTok URL or plain text description

    Returns:
    - 200: Place saved or requires confirmation
    - 400: Validation error (empty input)
    - 422: Extraction failed or unsupported input
    - 500: Internal error

    The service handles all extraction logic; this route is a facade.
    """
    return await service.run(request.raw_input, request.user_id)
