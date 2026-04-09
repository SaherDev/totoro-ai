"""Event handlers for domain events

Handlers wrap TasteModelService calls with error handling and Langfuse tracing.
Per ADR-043, failures are logged and traced but never propagated to user-facing
responses.
"""

import logging
from typing import TYPE_CHECKING

from langfuse import Langfuse

from totoro_ai.core.events.events import (
    OnboardingSignal,
    PersonalFactsExtracted,
    PlaceSaved,
    RecommendationAccepted,
    RecommendationRejected,
)

if TYPE_CHECKING:
    from totoro_ai.core.memory.service import UserMemoryService
    from totoro_ai.core.taste.service import TasteModelService

logger = logging.getLogger(__name__)


class EventHandlers:
    """Container for event handler functions"""

    def __init__(
        self,
        taste_service: "TasteModelService",
        memory_service: "UserMemoryService",
        langfuse: Langfuse | None = None,
    ) -> None:
        """Initialize handlers with dependencies

        Args:
            taste_service: TasteModelService instance
            memory_service: UserMemoryService instance
            langfuse: Optional Langfuse client for tracing
        """
        self.taste_service = taste_service
        self.memory_service = memory_service
        self.langfuse = langfuse

    async def on_place_saved(self, event: PlaceSaved) -> None:
        """Handle place saved event - log and trace via Langfuse"""
        try:
            await self.taste_service.handle_place_saved(
                user_id=event.user_id,
                place_ids=event.place_ids,
                place_metadata=event.place_metadata,
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message="PlaceSaved event handled",
                    level="info",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
        except Exception as exc:
            logger.error(
                f"Failed to update taste model on place save: {exc}",
                exc_info=True,
                extra={"user_id": event.user_id, "place_ids": event.place_ids},
            )
            if self.langfuse:
                self.langfuse.capture_message(
                    message=f"PlaceSaved handler error: {exc}",
                    level="error",
                    metadata={"event_id": event.event_id, "user_id": event.user_id},
                )
                self.langfuse.flush()

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
                f"Failed to save personal facts: {exc}",
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
