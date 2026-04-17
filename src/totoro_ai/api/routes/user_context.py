"""GET /v1/user/context — user taste context for the product UI."""

from fastapi import APIRouter, Depends, Query

from totoro_ai.api.deps import get_taste_service
from totoro_ai.api.schemas.user_context import ChipResponse, UserContextResponse
from totoro_ai.core.taste.service import TasteModelService

router = APIRouter()


@router.get("/user/context", response_model=UserContextResponse)
async def get_user_context(
    user_id: str = Query(..., description="User identifier"),  # noqa: B008
    taste_service: TasteModelService = Depends(get_taste_service),  # noqa: B008
) -> UserContextResponse:
    """Return saved places count and taste chips for a user.

    Reads from TasteModelService.get_taste_profile — no LLM call.
    Cold start (no taste profile): returns saved_places_count=0, chips=[].
    """
    profile = await taste_service.get_taste_profile(user_id)

    if profile is None:
        return UserContextResponse(saved_places_count=0, chips=[])

    saved_count: int = 0
    if isinstance(profile.signal_counts, dict):
        totals = profile.signal_counts.get("totals", {})
        if isinstance(totals, dict):
            saved_count = totals.get("saves", 0)

    chips = [
        ChipResponse(
            label=chip.label,
            source_field=chip.source_field,
            source_value=chip.source_value,
            signal_count=chip.signal_count,
        )
        for chip in profile.chips
    ]

    return UserContextResponse(saved_places_count=saved_count, chips=chips)
