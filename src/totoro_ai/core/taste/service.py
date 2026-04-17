"""TasteModelService — signal_counts + LLM summary + chips (ADR-058).

Replaces the former EMA-based taste model. All EMA logic is deleted.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from totoro_ai.core.config import get_config
from totoro_ai.core.taste.aggregation import aggregate_signal_counts
from totoro_ai.core.taste.regen import (
    build_regen_messages,
    validate_grounded,
)
from totoro_ai.core.taste.schemas import TasteArtifacts, TasteProfile
from totoro_ai.db.models import InteractionType
from totoro_ai.db.repositories.taste_model_repository import (
    SQLAlchemyTasteModelRepository,
)
from totoro_ai.providers.llm import get_llm

logger = logging.getLogger(__name__)


class TasteModelService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self._repo = SQLAlchemyTasteModelRepository(session_factory)
        self._config = get_config()

    async def handle_signal(
        self,
        user_id: str,
        signal_type: InteractionType,
        place_id: str,
    ) -> None:
        """Write interaction row, schedule debounced regen."""
        await self._repo.log_interaction(user_id, signal_type, place_id)

        # Import here to avoid circular dependency at module level
        from totoro_ai.core.taste.debounce import regen_debouncer

        regen_debouncer.schedule(
            user_id=user_id,
            coro_factory=lambda uid=user_id: self._run_regen(uid),
            delay_seconds=self._config.taste_model.debounce_window_seconds,
        )

    async def get_taste_profile(self, user_id: str) -> TasteProfile | None:
        """Read taste_model row. No LLM call."""
        taste_model = await self._repo.get_by_user_id(user_id)
        if taste_model is None:
            return None
        return TasteProfile(
            taste_profile_summary=taste_model.taste_profile_summary,
            signal_counts=taste_model.signal_counts,
            chips=taste_model.chips,
        )

    async def _run_regen(self, user_id: str) -> None:
        """Read interactions -> aggregate -> LLM artifacts -> validate -> write."""
        rows = await self._repo.get_interactions_with_places(user_id)

        # Min-signals guard
        if len(rows) < self._config.taste_model.regen.min_signals:
            return

        signal_counts = aggregate_signal_counts(rows)

        # Stale guard: skip if no new signals since last regen
        taste_model = await self._repo.get_by_user_id(user_id)
        if taste_model and taste_model.generated_from_log_count == len(rows):
            return

        # Build prompt and call LLM
        messages = build_regen_messages(
            signal_counts,
            self._config.taste_model.regen.early_signal_threshold,
        )
        artifacts = await self._call_llm_with_retry(messages)
        if artifacts is None:
            logger.warning(
                "Regen skipped for user %s: LLM parse failure", user_id
            )
            return

        # Validate grounding
        artifacts, dropped = validate_grounded(artifacts, signal_counts)

        # Langfuse trace metadata
        metadata: dict[str, Any] = {
            "user_id": user_id,
            "log_row_count": len(rows),
            "prior_log_count": (
                taste_model.generated_from_log_count if taste_model else 0
            ),
            "debounce_window_ms": (
                self._config.taste_model.debounce_window_seconds * 1000
            ),
        }
        if dropped:
            metadata["dropped_item_count"] = len(dropped)
            metadata["dropped_items"] = dropped

        logger.info(
            "Regen completed for user %s: "
            "%d summary lines, %d chips, %d dropped",
            user_id,
            len(artifacts.summary),
            len(artifacts.chips),
            len(dropped),
        )

        # Persist — repo commits internally
        await self._repo.upsert_regen(
            user_id=user_id,
            signal_counts=signal_counts.model_dump(exclude_defaults=False),
            summary=[line.model_dump() for line in artifacts.summary],
            chips=[chip.model_dump() for chip in artifacts.chips],
            log_count=len(rows),
        )

    async def _call_llm_with_retry(
        self, messages: list[dict[str, str]]
    ) -> TasteArtifacts | None:
        """Call LLM and parse into TasteArtifacts. Retry once on failure."""
        llm = get_llm("taste_regen")

        for attempt in range(2):
            try:
                raw = await llm.complete(messages)
                parsed = json.loads(raw)
                return TasteArtifacts.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as exc:
                if attempt == 0:
                    logger.warning(
                        "LLM parse attempt 1 failed, retrying: %s", exc
                    )
                else:
                    logger.error(
                        "LLM parse attempt 2 failed, skipping: %s", exc
                    )
                    return None
        return None
