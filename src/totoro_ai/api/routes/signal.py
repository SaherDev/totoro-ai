"""POST /v1/signal — behavioral signal endpoint (replaces /v1/feedback)."""

from fastapi import APIRouter, Depends, HTTPException, status

from totoro_ai.api.deps import get_signal_service
from totoro_ai.api.schemas.signal import SignalRequest, SignalResponse
from totoro_ai.core.signal.service import RecommendationNotFoundError, SignalService

router = APIRouter()


@router.post(
    "/signal", response_model=SignalResponse, status_code=status.HTTP_202_ACCEPTED
)
async def post_signal(
    request: SignalRequest,
    signal_service: SignalService = Depends(get_signal_service),  # noqa: B008
) -> SignalResponse:
    """Handle recommendation acceptance/rejection signals.

    Validates recommendation_id exists, dispatches event, returns 202.
    Handler runs as background task after HTTP response (ADR-043).
    Pydantic Literal type enforces signal_type — unknown types get 422.
    """
    try:
        await signal_service.handle_signal(
            signal_type=request.signal_type,
            user_id=request.user_id,
            recommendation_id=request.recommendation_id,
            place_id=request.place_id,
        )
    except RecommendationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found",
        ) from None

    return SignalResponse()
