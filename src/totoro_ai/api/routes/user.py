"""User-scoped routes (/v1/user/...): taste context fetch and AI-data erase."""

from fastapi import APIRouter, Depends, Query, status

from totoro_ai.api.deps import get_taste_service, get_user_data_deletion_service
from totoro_ai.core.taste.schemas import UserContext
from totoro_ai.core.taste.service import TasteModelService
from totoro_ai.core.user.service import UserDataDeletionService

router = APIRouter()


@router.get("/user/context", response_model=UserContext)
async def get_user_context(
    user_id: str = Query(..., description="User identifier"),  # noqa: B008
    taste_service: TasteModelService = Depends(get_taste_service),  # noqa: B008
) -> UserContext:
    """Thin facade — delegates to TasteModelService.get_user_context (ADR-034)."""
    return await taste_service.get_user_context(user_id)


@router.delete("/user/{user_id}/data", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_data(
    user_id: str,
    service: UserDataDeletionService = Depends(get_user_data_deletion_service),  # noqa: B008
) -> None:
    """Hard-delete every trace of a user's AI-owned data.

    Sweeps the 6 AI tables (embeddings cascade from places), deletes the
    LangGraph checkpoint thread (= agent history), and cancels any
    pending taste-regen task. Idempotent — calling on an absent user is
    still 204.

    Does NOT delete the user account — NestJS owns user lifecycle. The
    product repo calls this endpoint as part of its account-delete flow.
    """
    await service.delete_user_data(user_id)
