"""GET /v1/extraction/{request_id} — poll status of a background extraction."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from totoro_ai.api.deps import get_status_repo
from totoro_ai.api.schemas.extract_place import ExtractPlaceResponse
from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository

router = APIRouter()


@router.get("/extraction/{request_id}", status_code=200)
async def get_extraction_status(
    request_id: str,
    status_repo: ExtractionStatusRepository = Depends(get_status_repo),  # noqa: B008
) -> ExtractPlaceResponse:
    """Return the result of a background extraction keyed by request_id.

    Returns 404 if the key is not in Redis yet (still running or expired).
    """
    payload = await status_repo.read(request_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Extraction result not found")
    return ExtractPlaceResponse(**payload)
