"""TasteModelRepository — Protocol and implementation for taste model persistence"""

import math
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.db.models import InteractionLog, SignalType, TasteModel


class TasteModelRepository(Protocol):
    """Protocol for taste model repository operations"""

    async def get_by_user_id(self, user_id: str) -> TasteModel | None:
        """Retrieve a user's taste model profile

        Args:
            user_id: User identifier

        Returns:
            TasteModel if exists, None otherwise
        """
        ...

    async def upsert(
        self,
        user_id: str,
        parameters: dict[str, float],
    ) -> TasteModel:
        """Insert or update a taste model profile with atomic count increment

        interaction_count is incremented atomically in the DB (avoids
        read-modify-write race when concurrent signals arrive for the same user).
        confidence is recalculated in the same statement as
        1 − exp(−(count + 1) / 10).

        Args:
            user_id: User identifier
            parameters: 8-dimension taste vector {dimension: float}

        Returns:
            Persisted TasteModel record
        """
        ...

    async def log_interaction(
        self,
        user_id: str,
        signal_type: SignalType,
        place_id: str | None,
        gain: float,
        context: dict[str, Any],
    ) -> None:
        """Record a behavioral signal in the interaction log

        Args:
            user_id: User identifier
            signal_type: Type of signal (save, accepted, rejected, etc.)
            place_id: Place identifier (nullable for some signal types)
            gain: Signal strength/weight from config
            context: Additional context {location, time_of_day, session_id,
                recommendation_id}

        Raises:
            Exception: If log write fails, caller must abort cache update
        """
        ...


class SQLAlchemyTasteModelRepository:
    """SQLAlchemy implementation of TasteModelRepository"""

    def __init__(self, session: AsyncSession):
        """Initialize repository with async database session

        Args:
            session: AsyncSession for database operations
        """
        self.session = session

    async def get_by_user_id(self, user_id: str) -> TasteModel | None:
        """Retrieve a user's taste model profile"""
        stmt = select(TasteModel).where(TasteModel.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        user_id: str,
        parameters: dict[str, float],
    ) -> TasteModel:
        """Insert or update a taste model profile with atomic count increment

        interaction_count is incremented in SQL (interaction_count + 1) so two
        concurrent calls for the same user cannot both read count=5 and both
        write back 6, losing one increment.
        """
        # Atomic UPDATE: increment count and recompute confidence in one statement
        stmt = (
            update(TasteModel)
            .where(TasteModel.user_id == user_id)
            .values(
                parameters=parameters,
                interaction_count=TasteModel.interaction_count + 1,
                confidence=1
                - func.exp(-(TasteModel.interaction_count + 1) / 10.0),
            )
        )
        result = await self.session.execute(stmt)

        if result.rowcount > 0:  # type: ignore[attr-defined]
            # Re-fetch so the returned object reflects the DB state
            fetch = await self.session.execute(
                select(TasteModel).where(TasteModel.user_id == user_id)
            )
            return fetch.scalar_one()

        # New user — INSERT with count=1 and confidence = 1 − e^(−1/10)
        new_record = TasteModel(
            id=str(uuid4()),
            user_id=user_id,
            model_version="1.0",
            parameters=parameters,
            confidence=1 - math.exp(-1 / 10.0),
            interaction_count=1,
        )
        self.session.add(new_record)
        await self.session.flush()
        return new_record

    async def log_interaction(
        self,
        user_id: str,
        signal_type: SignalType,
        place_id: str | None,
        gain: float,
        context: dict[str, Any],
    ) -> None:
        """Record a behavioral signal in the interaction log

        Strict consistency: If this write fails, the caller MUST abort any
        cache updates. The interaction_log is the canonical source of truth
        for taste model state.
        """
        log_entry = InteractionLog(
            id=str(uuid4()),
            user_id=user_id,
            signal_type=signal_type,
            place_id=place_id,
            gain=gain,
            context=context,
        )
        self.session.add(log_entry)
        # Flush immediately — let exception propagate if write fails
        await self.session.flush()
