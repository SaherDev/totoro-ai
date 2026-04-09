"""Repository pattern for ConsultLog model (ADR-019).

Provides Protocol abstraction, a no-op stub, and the real SQLAlchemy
implementation for persisting consult log records.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from totoro_ai.db.models import ConsultLog

logger = logging.getLogger(__name__)


class ConsultLogRepository(Protocol):
    """Protocol for persisting consult log records."""

    async def save(self, log: ConsultLog) -> None:
        """Persist a consult log record.

        Args:
            log: ConsultLog instance to persist.
        """
        ...


class NullConsultLogRepository:
    """No-op implementation — used until the real DB impl is wired in."""

    async def save(self, log: ConsultLog) -> None:
        """No-op save — silently discards the log."""
        logger.debug("NullConsultLogRepository.save() called — no-op")


class SQLAlchemyConsultLogRepository:
    """SQLAlchemy async implementation of ConsultLogRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, log: ConsultLog) -> None:
        """Persist a consult log record via SQLAlchemy session.

        Args:
            log: ConsultLog instance to persist.
        """
        self._session.add(log)
        await self._session.commit()
