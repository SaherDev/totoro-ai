"""Database repository patterns.

Provides Protocol abstractions and concrete implementations for database access.
"""

from totoro_ai.db.repositories.embedding_repository import (
    EmbeddingRepository,
    SQLAlchemyEmbeddingRepository,
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
    "RecallRepository",
    "SQLAlchemyEmbeddingRepository",
    "SQLAlchemyRecallRepository",
    "TasteModelRepository",
    "SQLAlchemyTasteModelRepository",
]
