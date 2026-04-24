"""Erase a user's AI-owned data: SQL tables, LangGraph checkpoint thread,
and the in-memory taste-regen debouncer.

Scope note: this service does NOT delete the user account — that lives in
NestJS/Clerk in the product repo. This deletes only the data this repo
owns, called by NestJS as part of its account-delete flow.

Hard-delete only, idempotent (erasing a user with no data is a successful
no-op). See plan: hard-delete-only v1, sync sweep, 204 No Content.
"""

from __future__ import annotations

import asyncio
import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from totoro_ai.core.taste.debounce import RegenDebouncer
from totoro_ai.db.models import (
    Interaction,
    Place,
    Recommendation,
    TasteModel,
    UserMemory,
)

logger = logging.getLogger(__name__)

_CHECKPOINT_DELETE_MAX_ATTEMPTS = 3
_CHECKPOINT_DELETE_BACKOFF_BASE_SECONDS = 0.5


class UserDataDeletionService:
    """Erases every trace of a user's AI-owned data.

    Hits five tables in one transaction (embeddings cascade automatically
    from places via FK ON DELETE CASCADE — see db/models.py:96), then the
    LangGraph checkpoint thread (separate connection pool), then any
    in-flight taste-regen task in the in-memory debouncer.

    Does NOT delete the user account — NestJS owns user lifecycle. The
    product repo's account-delete flow calls this service to wipe the
    AI-side after deleting its own user/user_settings rows.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        checkpointer: AsyncPostgresSaver | None,
        regen_debouncer: RegenDebouncer,
    ) -> None:
        self._session_factory = session_factory
        self._checkpointer = checkpointer
        self._regen_debouncer = regen_debouncer

    async def delete_user_data(self, user_id: str) -> None:
        async with (
            self._session_factory() as session,
            session.begin(),
        ):
            await session.execute(
                delete(Interaction).where(Interaction.user_id == user_id)
            )
            await session.execute(
                delete(Recommendation).where(Recommendation.user_id == user_id)
            )
            await session.execute(
                delete(UserMemory).where(UserMemory.user_id == user_id)
            )
            await session.execute(
                delete(TasteModel).where(TasteModel.user_id == user_id)
            )
            await session.execute(
                delete(Place).where(Place.user_id == user_id)
            )

        if self._checkpointer is not None:
            await self._delete_thread_with_retry(user_id)
        else:
            logger.warning(
                "Skipping checkpointer.adelete_thread for user_id=%s — "
                "checkpointer is None (lifespan not run or warmup failed)",
                user_id,
            )

        self._regen_debouncer.cancel_pending(user_id)

    async def _delete_thread_with_retry(self, user_id: str) -> None:
        """Run `adelete_thread` with bounded retry.

        SQL deletes already committed by the time we get here, so a
        transient psycopg blip on the checkpointer connection pool would
        otherwise leave orphaned checkpoint rows that re-attach to the
        user_id on next signup (Clerk preserves IDs across recreate).
        Retry locally so NestJS doesn't have to drive recovery.
        """
        assert self._checkpointer is not None
        last_exc: Exception | None = None
        for attempt in range(_CHECKPOINT_DELETE_MAX_ATTEMPTS):
            try:
                await self._checkpointer.adelete_thread(user_id)
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "adelete_thread attempt %d/%d failed for user_id=%s: %s",
                    attempt + 1,
                    _CHECKPOINT_DELETE_MAX_ATTEMPTS,
                    user_id,
                    exc,
                )
                if attempt < _CHECKPOINT_DELETE_MAX_ATTEMPTS - 1:
                    await asyncio.sleep(
                        _CHECKPOINT_DELETE_BACKOFF_BASE_SECONDS * (2**attempt)
                    )
        assert last_exc is not None
        logger.error(
            "adelete_thread exhausted retries for user_id=%s — orphaned "
            "checkpoint rows will leak to the same user_id on next signup",
            user_id,
        )
        raise last_exc
