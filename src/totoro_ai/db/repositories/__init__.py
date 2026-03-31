"""Database repository patterns.

Provides Protocol abstractions and concrete implementations for database access.
"""

from totoro_ai.db.repositories.embedding_repository import (
    EmbeddingRepository,
    SQLAlchemyEmbeddingRepository,
)
from totoro_ai.db.repositories.place_repository import (
    PlaceRepository,
    SQLAlchemyPlaceRepository,
)
from totoro_ai.db.repositories.recall_repository import (
    RecallRepository,
    SQLAlchemyRecallRepository,
)
from totoro_ai.db.repositories.taste_model_repository import (
    SQLAlchemyTasteModelRepository,
    TasteModelRepository,
)

__all__ = [
    "EmbeddingRepository",
    "PlaceRepository",
    "RecallRepository",
    "SQLAlchemyEmbeddingRepository",
    "SQLAlchemyPlaceRepository",
    "SQLAlchemyRecallRepository",
    "TasteModelRepository",
    "SQLAlchemyTasteModelRepository",
]
