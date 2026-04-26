"""UserPlacesRepo — sole writer/reader of the user_places DB table."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PlaceSource, UserPlace

logger = logging.getLogger(__name__)


class UserPlacesRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user(self, user_id: str) -> list[UserPlace]:
        result = await self._session.execute(
            text(
                "SELECT * FROM user_places WHERE user_id = :uid ORDER BY saved_at DESC"
            ).bindparams(uid=user_id)
        )
        return [_row_to_user_place(row._mapping) for row in result]

    async def get_by_user_place_id(self, user_place_id: str) -> UserPlace | None:
        result = await self._session.execute(
            text(
                "SELECT * FROM user_places WHERE user_place_id = :upid"
            ).bindparams(upid=user_place_id)
        )
        row = result.mappings().first()
        return _row_to_user_place(row) if row else None

    async def save_user_places(
        self, user_places: list[UserPlace]
    ) -> list[UserPlace]:
        """INSERT or UPDATE on user_place_id primary key."""
        if not user_places:
            return []

        rows = [_user_place_to_dict(up) for up in user_places]

        stmt = (
            pg_insert(_UserPlacesTable)
            .values(rows)
            .on_conflict_do_update(
                index_elements=["user_place_id"],
                set_={
                    "needs_approval": text("EXCLUDED.needs_approval"),
                    "visited": text("EXCLUDED.visited"),
                    "liked": text("EXCLUDED.liked"),
                    "note": text("EXCLUDED.note"),
                    "visited_at": text("EXCLUDED.visited_at"),
                },
            )
            .returning(text("*"))
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return [_row_to_user_place(row._mapping) for row in result]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

from sqlalchemy import Column, MetaData, Table  # noqa: E402

_metadata = MetaData()
_UserPlacesTable = Table(
    "user_places",
    _metadata,
    Column("user_place_id"),
    Column("user_id"),
    Column("place_id"),
    Column("needs_approval"),
    Column("visited"),
    Column("liked"),
    Column("note"),
    Column("source"),
    Column("source_url"),
    Column("saved_at"),
    Column("visited_at"),
)


def _user_place_to_dict(up: UserPlace) -> dict[str, object]:
    return {
        "user_place_id": up.user_place_id,
        "user_id": up.user_id,
        "place_id": up.place_id,
        "needs_approval": up.needs_approval,
        "visited": up.visited,
        "liked": up.liked,
        "note": up.note,
        "source": up.source.value,
        "source_url": up.source_url,
        "saved_at": up.saved_at,
        "visited_at": up.visited_at,
    }


def _row_to_user_place(row: object) -> UserPlace:
    from collections.abc import Mapping

    m = dict(row) if isinstance(row, Mapping) else vars(row)
    return UserPlace(
        user_place_id=m["user_place_id"],
        user_id=m["user_id"],
        place_id=m["place_id"],
        needs_approval=bool(m.get("needs_approval", False)),
        visited=bool(m.get("visited", False)),
        liked=m.get("liked"),
        note=m.get("note"),
        source=PlaceSource(m["source"]),
        source_url=m.get("source_url"),
        saved_at=m["saved_at"],
        visited_at=m.get("visited_at"),
    )
