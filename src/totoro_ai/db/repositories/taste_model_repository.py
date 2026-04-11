import math
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.db.models import InteractionLog, SignalType, TasteModel


class TasteModelRepository(Protocol):
    async def get_by_user_id(self, user_id: str) -> TasteModel | None: ...

    async def upsert(
        self,
        user_id: str,
        parameters: dict[str, float],
    ) -> TasteModel: ...

    async def log_interaction(
        self,
        user_id: str,
        signal_type: SignalType,
        place_id: str | None,
        gain: float,
        context: dict[str, Any],
    ) -> None: ...


class SQLAlchemyTasteModelRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: str) -> TasteModel | None:
        stmt = select(TasteModel).where(TasteModel.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        user_id: str,
        parameters: dict[str, float],
    ) -> TasteModel:
        stmt = (
            update(TasteModel)
            .where(TasteModel.user_id == user_id)
            .values(
                parameters=parameters,
                interaction_count=TasteModel.interaction_count + 1,
                confidence=1 - func.exp(-(TasteModel.interaction_count + 1) / 10.0),
            )
        )
        result = await self.session.execute(stmt)

        if result.rowcount > 0:  # type: ignore[attr-defined]
            fetch = await self.session.execute(
                select(TasteModel).where(TasteModel.user_id == user_id)
            )
            return fetch.scalar_one()

        insert_stmt = (
            pg_insert(TasteModel)
            .values(
                id=str(uuid4()),
                user_id=user_id,
                model_version="1.0",
                parameters=parameters,
                confidence=1 - math.exp(-1 / 10.0),
                interaction_count=1,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_=dict(
                    parameters=parameters,
                    interaction_count=TasteModel.interaction_count + 1,
                    confidence=1 - func.exp(-(TasteModel.interaction_count + 1) / 10.0),
                ),
            )
        )
        await self.session.execute(insert_stmt)
        fetch = await self.session.execute(
            select(TasteModel).where(TasteModel.user_id == user_id)
        )
        return fetch.scalar_one()

    async def log_interaction(
        self,
        user_id: str,
        signal_type: SignalType,
        place_id: str | None,
        gain: float,
        context: dict[str, Any],
    ) -> None:
        log_entry = InteractionLog(
            id=str(uuid4()),
            user_id=user_id,
            signal_type=signal_type,
            place_id=place_id,
            gain=gain,
            context=context,
        )
        self.session.add(log_entry)
        await self.session.flush()
