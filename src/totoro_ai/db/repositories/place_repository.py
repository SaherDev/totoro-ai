"""Repository pattern implementation for Place model.

Provides Protocol and implementation for database operations on Place entities.
Handles upsert semantics (save) and lookup (get_by_provider) with error recovery.
"""

import logging
from typing import Protocol, cast

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.core.config import get_config
from totoro_ai.db.models import Place

logger = logging.getLogger(__name__)


class PlaceRepository(Protocol):
    """Protocol for Place repository operations.

    Defines the interface for database access to places. Implementations must:
    - get_by_provider(): Return existing place by (provider, external_id)
    - save(): Insert new place or update existing (upsert semantics)
    """

    async def get_by_id(self, place_id: str) -> Place | None:
        """Get place by primary key."""
        ...

    async def get_by_provider(self, provider: str, external_id: str) -> Place | None:
        """Get place by provider and external ID.

        Args:
            provider: External provider name (e.g., 'google', 'yelp')
            external_id: Provider's unique ID for the place

        Returns:
            Place record if found, None otherwise
        """
        ...

    async def save(self, place: Place) -> Place:
        """Save place to database (insert or update).

        Implements upsert semantics:
        - If (provider, external_id) exists: update all mutable fields
        - If not exists: insert new record
        - On error: rollback, log with context, raise RuntimeError

        Args:
            place: Place entity to save

        Returns:
            Saved Place record (newly inserted or updated)

        Raises:
            RuntimeError: If save operation fails (with cause chain via __cause__)
        """
        ...

    async def save_many(self, places: list[Place]) -> list[Place]:
        """Save multiple places in a single transaction.

        Batch dedup lookup + insert/update + single commit.

        Args:
            places: List of Place entities to save

        Returns:
            List of saved Place records (matching input order)
        """
        ...


class SQLAlchemyPlaceRepository:
    """SQLAlchemy implementation of PlaceRepository.

    Handles async operations with explicit error recovery (rollback + logging).
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            session: AsyncSession for database operations
        """
        self._session = session

    async def get_by_id(self, place_id: str) -> Place | None:
        return cast(
            Place | None,
            await self._session.scalar(select(Place).where(Place.id == place_id)),
        )

    async def get_by_provider(self, provider: str, external_id: str) -> Place | None:
        """Get place by provider and external ID.

        Args:
            provider: External provider name
            external_id: Provider's unique ID for the place

        Returns:
            Place record if found, None otherwise
        """
        return cast(
            Place | None,
            await self._session.scalar(
                select(Place).filter_by(
                    external_provider=provider, external_id=external_id
                )
            ),
        )

    async def save(self, place: Place) -> Place:
        """Save place to database (insert or update).

        Implements upsert logic:
        1. If place has external_id, attempt dedup lookup
        2. If found, update all mutable fields
        3. If not found, insert as new record
        4. On any error: rollback, log with context, re-raise as RuntimeError

        Args:
            place: Place entity to save

        Returns:
            Saved Place record

        Raises:
            RuntimeError: If save fails (includes provider, external_id in message)
        """
        try:
            config = get_config()
            mutable_fields = config.extraction.mutable_fields

            existing: Place | None = None

            # Only attempt dedup if external_id is not None
            if place.external_id is not None:
                existing = await self.get_by_provider(
                    place.external_provider, place.external_id
                )

            if existing is not None:
                # Update mutable fields on existing record
                for field in mutable_fields:
                    setattr(existing, field, getattr(place, field))
                await self._session.commit()
                return existing

            # Insert new record
            self._session.add(place)
            await self._session.commit()
            return place

        except Exception as e:
            await self._session.rollback()
            logger.error(
                "Failed to save place",
                extra={
                    "external_provider": place.external_provider,
                    "external_id": place.external_id,
                    "error": str(e),
                },
            )
            raise RuntimeError(
                f"Failed to save place "
                f"({place.external_provider}/{place.external_id}): {e}"
            ) from e

    async def save_many(self, places: list[Place]) -> list[Place]:
        """Save multiple places in a single transaction.

        1. Batch dedup: one SELECT for all (provider, external_id) pairs
        2. Update existing, add new
        3. Single commit

        Args:
            places: List of Place entities to save

        Returns:
            List of saved Place records (matching input order)
        """
        if not places:
            return []

        try:
            config = get_config()
            mutable_fields = config.extraction.mutable_fields

            # Batch dedup lookup — one query for all pairs
            pairs = [
                (p.external_provider, p.external_id)
                for p in places
                if p.external_id is not None
            ]

            existing_map: dict[tuple[str, str], Place] = {}
            if pairs:
                stmt = select(Place).where(
                    tuple_(
                        Place.external_provider, Place.external_id
                    ).in_(pairs)
                )
                result = await self._session.execute(stmt)
                for row in result.scalars().all():
                    key = (row.external_provider, row.external_id or "")
                    existing_map[key] = row

            # Process each place: update existing or insert new
            saved: list[Place] = []
            for place in places:
                key = (place.external_provider, place.external_id or "")
                existing = existing_map.get(key)

                if existing is not None:
                    for field in mutable_fields:
                        setattr(existing, field, getattr(place, field))
                    saved.append(existing)
                else:
                    self._session.add(place)
                    saved.append(place)

            await self._session.commit()
            return saved

        except Exception as e:
            await self._session.rollback()
            logger.error(
                "Failed to save %d places: %s",
                len(places),
                e,
            )
            raise RuntimeError(
                f"Failed to save {len(places)} places: {e}"
            ) from e
