"""Recall endpoint route handler (facade)."""

from fastapi import APIRouter, Depends

from totoro_ai.api.deps import get_recall_service
from totoro_ai.api.schemas.recall import RecallRequest, RecallResponse
from totoro_ai.core.recall.service import RecallService

router = APIRouter()


@router.post("/recall", response_model=RecallResponse)
async def recall(
    request: RecallRequest,
    service: RecallService = Depends(get_recall_service),  # noqa: B008
) -> RecallResponse:
    """Recall endpoint — hybrid search over user's saved places.

    Request: query (natural language), user_id (from auth)
    Response: results (list), total (count), empty_state (boolean)
    """
    return await service.run(request.query, request.user_id)
