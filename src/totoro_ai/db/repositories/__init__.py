"""Database repository patterns.

Provides Protocol abstractions and concrete implementations for database access.
"""

from totoro_ai.db.repositories.place_repository import (
    PlaceRepository,
    SQLAlchemyPlaceRepository,
)

__all__ = ["PlaceRepository", "SQLAlchemyPlaceRepository"]
