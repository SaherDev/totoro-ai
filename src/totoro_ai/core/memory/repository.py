"""Repository abstractions for user memory persistence (ADR-038)."""

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class UserMemoryRepository(Protocol):
    """Protocol for user memory persistence (ADR-038).

    Abstraction allowing swappable storage implementations.
    """

    async def save(
        self,
        user_id: str,
        memory: str,
        source: str,
        confidence: float,
    ) -> None:
        """Persist a personal fact.

        Idempotent — duplicate (user_id, memory) is silently skipped
        by database UNIQUE constraint (INSERT ON CONFLICT DO NOTHING).

        Args:
            user_id: User identity
            memory: Plain-text declarative fact
            source: "stated" or "inferred"
            confidence: 0.9 for stated, 0.6 for inferred
        """
        ...

    async def load(self, user_id: str) -> list[str]:
        """Load all stored memory strings for user_id.

        Returns [] if none exist or on failure — callers must handle empty list.
        Ordered by created_at ASC (oldest first).

        Args:
            user_id: User identity

        Returns:
            list[str]: Plain text memory strings, or [] on failure
        """
        ...


class NullUserMemoryRepository:
    """No-op implementation for testing (ADR-038)."""

    async def save(
        self,
        user_id: str,
        memory: str,
        source: str,
        confidence: float,
    ) -> None:
        """No-op."""
        pass

    async def load(self, user_id: str) -> list[str]:
        """Always return empty list."""
        return []


class SQLAlchemyUserMemoryRepository:
    """SQLAlchemy async implementation with deduplication (ADR-038).

    Access: only instantiated in api/deps.py get_user_memory_service().
    No other class holds a direct reference to this implementation.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def save(
        self,
        user_id: str,
        memory: str,
        source: str,
        confidence: float,
    ) -> None:
        """Persist a personal fact using INSERT ON CONFLICT DO NOTHING.

        Deduplicates on (user_id, memory) via database UNIQUE constraint.
        Exact duplicate — same user, same text — is silently skipped.

        Args:
            user_id: User identity
            memory: Plain-text declarative fact
            source: "stated" or "inferred"
            confidence: 0.9 for stated, 0.6 for inferred
        """
        from uuid import uuid4

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from totoro_ai.db.models import UserMemory

        stmt = (
            pg_insert(UserMemory)
            .values(
                id=str(uuid4()),
                user_id=user_id,
                memory=memory,
                source=source,
                confidence=confidence,
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "memory"],
            )
        )
        await self.db_session.execute(stmt)

    async def load(self, user_id: str) -> list[str]:
        """Load all stored memory strings for user_id, ordered by created_at ASC.

        Returns [] on any failure — never raises.

        Args:
            user_id: User identity

        Returns:
            list[str]: Plain text memory strings, or [] on failure
        """
        from totoro_ai.db.models import UserMemory

        try:
            stmt = (
                select(UserMemory.memory)
                .where(UserMemory.user_id == user_id)
                .order_by(UserMemory.created_at.asc())
            )
            result = await self.db_session.execute(stmt)
            return [row[0] for row in result.all()]
        except Exception:
            return []
