"""User-scoped routes (/v1/user/...): taste context fetch and AI-data erase."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from totoro_ai.api.deps import (
    get_places_service,
    get_taste_service,
    get_user_data_deletion_service,
)
from totoro_ai.core.places.service import PlacesService
from totoro_ai.core.taste.schemas import UserContext
from totoro_ai.core.taste.service import TasteModelService
from totoro_ai.core.user.service import DataScope, UserDataDeletionService

router = APIRouter()


def _parse_scope_query(raw: str | None) -> set[DataScope] | None:
    """Parse the comma-separated `scope` query param into a set of scopes.

    `None` (param omitted or empty) → returns `None` so the service
    applies its default (wipe everything). Unknown values raise 400.
    """
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    valid = {s.value for s in DataScope}
    invalid = [p for p in parts if p not in valid]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown scope(s): {invalid}. "
                f"Valid values: {sorted(valid)}"
            ),
        )
    return {DataScope(p) for p in parts}


@router.get("/user/context", response_model=UserContext)
async def get_user_context(
    user_id: str = Query(..., description="User identifier"),  # noqa: B008
    taste_service: TasteModelService = Depends(get_taste_service),  # noqa: B008
    places_service: PlacesService = Depends(get_places_service),  # noqa: B008
) -> UserContext:
    """Compose `saved_places_count` (from the `places` table via
    PlacesService) with the taste-model-derived tier + chips. The count
    is owned outside TasteModelService so cold users (no taste_model row
    yet) still see their real save total.
    """
    saved_places_count = await places_service.count_for_user(user_id)
    taste_context = await taste_service.get_taste_context(user_id)
    return UserContext(
        saved_places_count=saved_places_count,
        signal_tier=taste_context.signal_tier,
        chips=taste_context.chips,
    )


@router.delete("/user/{user_id}/data", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_data(
    user_id: str,
    scope: str | None = Query(  # noqa: B008
        default=None,
        description=(
            "Comma-separated list of data scopes to delete. Valid: "
            "'all', 'chat_history'. Omit (or use 'all') to wipe "
            "everything — current behavior preserved for the NestJS "
            "account-delete flow."
        ),
    ),
    service: UserDataDeletionService = Depends(get_user_data_deletion_service),  # noqa: B008
) -> None:
    """Selectively delete a user's AI-owned data.

    Default (no `scope`): hard-deletes every trace — sweeps the 6 AI
    tables (embeddings cascade from places), deletes the LangGraph
    checkpoint thread, and cancels any pending taste-regen task.
    Idempotent — calling on an absent user is still 204.

    `scope=chat_history`: clears only the LangGraph checkpoint thread
    + pending taste-regen. Saves stay intact. Useful for resetting an
    agent that learned a stale pattern (e.g. a URL that used to time
    out) without losing the user's data.

    Does NOT delete the user account — NestJS owns user lifecycle. The
    product repo calls this endpoint as part of its account-delete flow
    (no `scope`).
    """
    scopes = _parse_scope_query(scope)
    await service.delete_user_data(user_id, scopes=scopes)
