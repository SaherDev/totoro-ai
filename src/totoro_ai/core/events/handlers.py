"""Event handlers for domain events

Handlers wrap TasteModelService calls with error handling and Langfuse tracing.
Per ADR-043, failures are logged and traced but never propagated to user-facing
responses.
"""

import logging
from typing import TYPE_CHECKING

from langfuse import Langfuse

from totoro_ai.core.events.events import (
    ExtractionPending,
    OnboardingSignal,
    PlaceSaved,
    RecommendationAccepted,
    RecommendationRejected,
)

if TYPE_CHECKING:
    from totoro_ai.core.taste.service import TasteModelService

logger = logging.getLogger(__name__)


class EventHandlers:
    """Container for event handler functions"""

    def __init__(
        self, taste_service: "TasteModelService", langfuse: Langfuse | None = None
    ) -> None:
        """Initialize handlers with dependencies

        Args:
            taste_service: TasteModelService instance
            langfuse: Optional Langfuse client for tracing
        """
        self.taste_service = taste_service
        self.langfuse = langfuse

    async def on_place_saved(self, event: PlaceSaved) -> None:
        """Handle place saved event — batch update taste model for all places."""
        for i, place_id in enumerate(event.place_ids):
            metadata = event.place_metadata[i] if i < len(event.place_metadata) else {}
            try:
                await self.taste_service.handle_place_saved(
                    user_id=event.user_id,
                    place_id=place_id,
                    place_metadata=metadata,
                )
            except Exception as exc:
                logger.error(
                    "Failed to update taste model on place save: %s",
                    exc,
                    exc_info=True,
                    extra={"user_id": event.user_id, "place_id": place_id},
                )
                if self.langfuse:
                    self.langfuse.capture_message(
                        message=f"PlaceSaved handler error: {exc}",
                        level="error",
                        metadata={
                            "event_id": event.event_id,
                            "user_id": event.user_id,
                            "place_id": place_id,
                        },
                    )
                    self.langfuse.flush()

        if self.langfuse:
            self.langfuse.capture_message(
                message="PlaceSaved event handled",
                level="info",
                metadata={
                    "event_id": event.event_id,
                    "user_id": event.user_id,
                    "place_count": len(event.place_ids),
                },
            )

    async def on_extraction_pending(self, event: ExtractionPending) -> None:
        """Handle extraction pending event — stub for background processing."""
        logger.info(
            "ExtractionPending received for user %s, url=%s, levels=%s",
            event.user_id,
            event.url,
            event.pending_levels,
        )

    async def on_recommendation_accepted(self, event: RecommendationAccepted) -> None:
        """Handle recommendation accepted event - log and trace via Langfuse"""
        try:
            await self.taste_service.handle_recommendation_accepted(
                user_id=event.user_id,
                place_id=event.place_id,
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message="RecommendationAccepted event handled",
                    level="info",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
        except Exception as exc:
            logger.error(
                f"Failed to update taste model on recommendation accept: {exc}",
                exc_info=True,
                extra={"user_id": event.user_id, "place_id": event.place_id},
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message=f"RecommendationAccepted handler error: {exc}",
                    level="error",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
                self.langfuse.flush()

    async def on_recommendation_rejected(self, event: RecommendationRejected) -> None:
        """Handle recommendation rejected event - log and trace via Langfuse"""
        try:
            await self.taste_service.handle_recommendation_rejected(
                user_id=event.user_id,
                place_id=event.place_id,
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message="RecommendationRejected event handled",
                    level="info",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
        except Exception as exc:
            logger.error(
                f"Failed to update taste model on recommendation reject: {exc}",
                exc_info=True,
                extra={"user_id": event.user_id, "place_id": event.place_id},
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message=f"RecommendationRejected handler error: {exc}",
                    level="error",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
                self.langfuse.flush()

    async def on_onboarding_signal(self, event: OnboardingSignal) -> None:
        """Handle onboarding signal event - log and trace via Langfuse"""
        try:
            await self.taste_service.handle_onboarding_signal(
                user_id=event.user_id,
                place_id=event.place_id,
                confirmed=event.confirmed,
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message="OnboardingSignal event handled",
                    level="info",
                    metadata={
                        "event_id": event.event_id,
                        "user_id": event.user_id,
                        "confirmed": event.confirmed,
                    },
                )
        except Exception as exc:
            logger.error(
                f"Failed to update taste model on onboarding signal: {exc}",
                exc_info=True,
                extra={
                    "user_id": event.user_id,
                    "place_id": event.place_id,
                    "confirmed": event.confirmed,
                },
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message=f"OnboardingSignal handler error: {exc}",
                    level="error",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
                self.langfuse.flush()
