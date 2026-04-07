"""extract-place endpoints: POST + GET /status (ADR-034, ADR-048)."""

from typing import Any

from fastapi import APIRouter, Depends

from totoro_ai.api.deps import get_extraction_service, get_status_repo
from totoro_ai.api.schemas.extract_place import (
    ExtractPlaceRequest,
    ExtractPlaceResponse,
)
from totoro_ai.core.extraction.service import ExtractionService
from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository

router = APIRouter()


@router.post("/extract-place", response_model=ExtractPlaceResponse)
async def extract_place(
    request: ExtractPlaceRequest,
    service: ExtractionService = Depends(get_extraction_service),  # noqa: B008
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


@router.get("/extract-place/status/{request_id}")
async def get_extraction_status(
    request_id: str,
    status_repo: ExtractionStatusRepository = Depends(get_status_repo),  # noqa: B008
) -> dict[str, Any]:
    """Poll extraction status for a provisional request (ADR-048).

    Returns the full ExtractPlaceResponse-compatible dict when complete,
    or {"extraction_status": "processing"} while pending or for unknown IDs.
    Always returns HTTP 200 — no 4xx for unknown/expired request_ids.
    """
    result = await status_repo.read(request_id)
    return result if result is not None else {"extraction_status": "processing"}
