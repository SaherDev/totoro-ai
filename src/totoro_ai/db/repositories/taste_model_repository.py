"""TasteModelRepository — Protocol and implementation for taste model persistence"""

from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import func, select
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
        confidence: float,
        interaction_count: int,
    ) -> TasteModel:
        """Insert or update a taste model profile

        Args:
            user_id: User identifier
            parameters: 8-dimension taste vector {dimension: float}
            confidence: Confidence score [0, 1] calculated as 1 − e^(−count / 10)
            interaction_count: Total interaction count

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
            context: Additional context {location, time_of_day, session_id, recommendation_id}

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
        confidence: float,
        interaction_count: int,
    ) -> TasteModel:
        """Insert or update a taste model profile with atomic increment"""
        # Get existing record
        stmt = select(TasteModel).where(TasteModel.user_id == user_id)
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing record
            existing.parameters = parameters
            existing.confidence = confidence
            existing.interaction_count = interaction_count
            await self.session.flush()
            return existing
        else:
            # Create new record
            new_record = TasteModel(
                id=str(uuid4()),
                user_id=user_id,
                model_version="1.0",  # Initial version
                parameters=parameters,
                confidence=confidence,
                interaction_count=interaction_count,
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

        Strict consistency: If this write fails, the caller MUST abort any cache updates.
        The interaction_log is the canonical source of truth for taste model state.
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
