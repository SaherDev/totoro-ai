"""Event handlers for domain events (ADR-058 simplified).

One taste handler (`on_taste_signal`) covers all 4 taste event types.
Per ADR-043, failures are logged and traced but never propagated.
"""

import logging
from typing import TYPE_CHECKING

from langfuse import Langfuse

from totoro_ai.core.events.events import (
    ChipConfirmed,
    DomainEvent,
    OnboardingSignal,
    PersonalFactsExtracted,
    PlaceSaved,
    RecommendationAccepted,
    RecommendationRejected,
)
from totoro_ai.db.models import InteractionType

if TYPE_CHECKING:
    from totoro_ai.core.memory.service import UserMemoryService
    from totoro_ai.core.taste.service import TasteModelService

logger = logging.getLogger(__name__)

# Map event_type → (InteractionType, how to get place_ids)
_TASTE_EVENT_MAP: dict[str, InteractionType] = {
    "recommendation_accepted": InteractionType.ACCEPTED,
    "recommendation_rejected": InteractionType.REJECTED,
}


class EventHandlers:
    """Container for event handler functions."""

    def __init__(
        self,
        taste_service: "TasteModelService",
        memory_service: "UserMemoryService",
        langfuse: Langfuse | None = None,
    ) -> None:
        self.taste_service = taste_service
        self.memory_service = memory_service
        self.langfuse = langfuse

    async def on_taste_signal(self, event: DomainEvent) -> None:
        """Unified handler for all taste-related events.

        Dispatches to handle_signal with the correct InteractionType.
        Handles PlaceSaved (multiple place_ids), RecommendationAccepted,
        RecommendationRejected, and OnboardingSignal.
        """
        try:
            # Build (signal_type, place_id) pairs from the event shape
            pairs: list[tuple[InteractionType, str]] = []
            if isinstance(event, PlaceSaved):
                pairs = [(InteractionType.SAVE, pid) for pid in event.place_ids]
            elif isinstance(event, OnboardingSignal):
                st = (
                    InteractionType.ONBOARDING_CONFIRM
                    if event.confirmed
                    else InteractionType.ONBOARDING_DISMISS
                )
                pairs = [(st, event.place_id)]
            elif isinstance(event, RecommendationAccepted | RecommendationRejected):
                pairs = [(_TASTE_EVENT_MAP[event.event_type], event.place_id)]

            for signal_type, place_id in pairs:
                await self.taste_service.handle_signal(
                    user_id=event.user_id,
                    signal_type=signal_type,
                    place_id=place_id,
                )

            if self.langfuse:
                self.langfuse.capture_message(
                    message=f"{event.event_type} handled",
                    level="info",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
        except Exception as exc:
            logger.error(
                "Failed to handle taste signal (%s): %s",
                event.event_type,
                exc,
                exc_info=True,
                extra={"user_id": event.user_id, "event_type": event.event_type},
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message=f"{event.event_type} handler error: {exc}",
                    level="error",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
                self.langfuse.flush()

    async def on_chip_confirmed(self, event: DomainEvent) -> None:
        """Handle ChipConfirmed — force an immediate taste-profile rewrite.

        Chip confirmation is an explicit user action; debouncing would make
        the summary rewrite feel disconnected from the action. Bypasses the
        debouncer via run_regen_now. Failures are logged via Langfuse per
        ADR-025 but never re-raised (ADR-043).
        """
        if not isinstance(event, ChipConfirmed):
            return
        try:
            await self.taste_service.run_regen_now(event.user_id)
            if self.langfuse:
                self.langfuse.capture_message(
                    message="chip_confirmed_regen handled",
                    level="info",
                    metadata={
                        "event_id": event.event_id,
                        "user_id": event.user_id,
                    },
                )
        except Exception as exc:
            logger.error(
                "Failed chip_confirmed_regen for user %s: %s",
                event.user_id,
                exc,
                exc_info=True,
                extra={"user_id": event.user_id, "event_type": event.event_type},
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message=f"chip_confirmed_regen error: {exc}",
                    level="error",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
                self.langfuse.flush()

    async def on_personal_facts_extracted(self, event: PersonalFactsExtracted) -> None:
        """Handle personal facts extracted event - persist to user_memories.

        Skips if personal_facts is empty. Catches and logs all exceptions
        via Langfuse; never raises (per ADR-043: failures don't block responses).
        """
        if not event.personal_facts:
            return

        try:
            from totoro_ai.core.config import get_config

            config = get_config()
            await self.memory_service.save_facts(
                user_id=event.user_id,
                facts=event.personal_facts,
                confidence_config=config.memory.confidence,
            )

            if self.langfuse:
                self.langfuse.capture_message(
                    message="PersonalFactsExtracted event handled",
                    level="info",
                    metadata={
                        "event_id": event.event_id,
                        "user_id": event.user_id,
                        "facts_count": len(event.personal_facts),
                    },
                )
        except Exception as exc:
            logger.error(
                "Failed to save personal facts: %s",
                exc,
                exc_info=True,
                extra={
                    "user_id": event.user_id,
                    "facts_count": len(event.personal_facts),
                },
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message=f"PersonalFactsExtracted handler error: {exc}",
                    level="error",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
                self.langfuse.flush()
