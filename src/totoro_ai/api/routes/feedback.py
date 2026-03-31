"""POST /v1/feedback endpoint for recommendation feedback signals"""

from fastapi import APIRouter, Depends, status

from totoro_ai.api.deps import get_event_dispatcher
from totoro_ai.api.schemas.feedback import FeedbackRequest, FeedbackResponse
from totoro_ai.core.events.dispatcher import EventDispatcher
from totoro_ai.core.events.events import (
    RecommendationAccepted,
    RecommendationRejected,
)

router = APIRouter()


@router.post(
    "/feedback", response_model=FeedbackResponse, status_code=status.HTTP_200_OK
)
async def post_feedback(
    request: FeedbackRequest,
    event_dispatcher: EventDispatcher = Depends(get_event_dispatcher),  # noqa: B008
) -> FeedbackResponse:
    """Handle recommendation acceptance/rejection feedback.

    Called by NestJS (product repo) after user taps feedback affordance in
    frontend. Dispatches event to update taste model asynchronously.

    Request:
        user_id: User identifier (injected by NestJS from Clerk auth token)
        recommendation_id: ID of the recommendation being responded to
        place_id: The place the user acted on (primary or alternative)
        signal: "accepted" or "rejected"

    Response:
        status: "received" — signal received and queued for processing

    Behavior:
        - Dispatches event immediately
        - Returns 200 without waiting for taste model update
        - Taste model update runs as background task after HTTP 200 response
        - Handler failures are logged and traced via Langfuse, never surfaced
          to user

    Notes:
        - recommendation_id is stored in interaction_log.context for
          traceability
        - Background failures never cause a failed HTTP response (per ADR-043)
    """
    event: RecommendationAccepted | RecommendationRejected
    if request.signal == "accepted":
        event = RecommendationAccepted(
            user_id=request.user_id,
            recommendation_id=request.recommendation_id,
            place_id=request.place_id,
        )
    else:  # rejected
        event = RecommendationRejected(
            user_id=request.user_id,
            recommendation_id=request.recommendation_id,
            place_id=request.place_id,
        )

    # Dispatch event (handler runs as background task after HTTP 200)
    await event_dispatcher.dispatch(event)

    return FeedbackResponse(status="received")
