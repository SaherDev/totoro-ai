"""User-scoped routes (/v1/user/...): taste context fetch and account erase."""

from fastapi import APIRouter, Depends, Query, status

from totoro_ai.api.deps import get_taste_service, get_user_deletion_service
from totoro_ai.core.taste.schemas import UserContext
from totoro_ai.core.taste.service import TasteModelService
from totoro_ai.core.user.service import UserDeletionService

router = APIRouter()


@router.get("/user/context", response_model=UserContext)
async def get_user_context(
    user_id: str = Query(..., description="User identifier"),  # noqa: B008
    taste_service: TasteModelService = Depends(get_taste_service),  # noqa: B008
) -> UserContext:
    """Thin facade — delegates to TasteModelService.get_user_context (ADR-034)."""
    return await taste_service.get_user_context(user_id)


@router.delete("/user/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    service: UserDeletionService = Depends(get_user_deletion_service),  # noqa: B008
) -> None:
    """Hard-delete every trace of a user from AI-owned storage.

    Sweeps the 6 AI tables (embeddings cascade from places), deletes the
    LangGraph checkpoint thread (= agent history), and cancels any
    pending taste-regen task. Idempotent — calling on an absent user is
    still 204.
    """
    await service.delete_user(user_id)
