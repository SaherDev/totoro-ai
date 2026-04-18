"""GET /v1/user/context — user taste context for the product UI."""

from fastapi import APIRouter, Depends, Query

from totoro_ai.api.deps import get_taste_service
from totoro_ai.core.taste.schemas import UserContext
from totoro_ai.core.taste.service import TasteModelService

router = APIRouter()


@router.get("/user/context", response_model=UserContext)
async def get_user_context(
    user_id: str = Query(..., description="User identifier"),  # noqa: B008
    taste_service: TasteModelService = Depends(get_taste_service),  # noqa: B008
) -> UserContext:
    """Thin facade — delegates to TasteModelService.get_user_context (ADR-034)."""
    return await taste_service.get_user_context(user_id)
