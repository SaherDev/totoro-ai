"""Repository pattern for recall hybrid search.

Implements Protocol + SQLAlchemy concrete class for pgvector + FTS + RRF query.
"""

import logging
from typing import Any, Protocol, TypedDict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class RecallRow(TypedDict):
    """Search result row from hybrid_search query."""

    place_id: str
    place_name: str
    address: str
    cuisine: str | None
    price_range: str | None
    source_url: str | None
    saved_at: Any  # datetime
    match_reason: str


class RecallRepository(Protocol):
    """Protocol for recall search operations."""

    async def hybrid_search(
        self,
        user_id: str,
        query_vector: list[float] | None,
        query_text: str,
        limit: int,
        rrf_k: int,
        candidate_multiplier: int,
    ) -> list[RecallRow]:
        """Hybrid search combining pgvector + FTS + RRF.

        Args:
            user_id: User ID to scope results
            query_vector: Query embedding (1024-dim). None triggers text-only fallback.
            query_text: Raw query text for FTS
            limit: Max results to return
            rrf_k: RRF constant (typically 60)
            candidate_multiplier: Pre-fetch N×limit candidates before RRF merge

        Returns:
            List of RecallRow dicts ordered by RRF score descending
        """
        ...

    async def count_saved_places(self, user_id: str) -> int:
        """Count user's saved places."""
        ...


class SQLAlchemyRecallRepository:
    """SQLAlchemy implementation of RecallRepository using raw SQL CTE."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def count_saved_places(self, user_id: str) -> int:
        """Count user's saved places."""
        query = text("SELECT COUNT(*) FROM places WHERE user_id = :user_id")
        result = await self._session.scalar(query, {"user_id": user_id})
        return result or 0

    async def hybrid_search(
        self,
        user_id: str,
        query_vector: list[float] | None,
        query_text: str,
        limit: int,
        rrf_k: int,
        candidate_multiplier: int,
    ) -> list[RecallRow]:
        """Hybrid search: vector + text + RRF merge (or text-only if vector is None).

        If query_vector is not None: full hybrid CTE with vector + text + RRF.
        If query_vector is None: text-only search with ts_rank ordering.
        """
        try:
            if query_vector is not None:
                return await self._hybrid_vector_text_search(
                    user_id,
                    query_vector,
                    query_text,
                    limit,
                    rrf_k,
                    candidate_multiplier,
                )
            else:
                return await self._text_only_search(user_id, query_text, limit)

        except Exception as e:
            logger.error(
                "Recall search failed",
                extra={"user_id": user_id, "error": str(e)},
            )
            raise RuntimeError(f"Failed to perform recall search: {e}") from e

    async def _hybrid_vector_text_search(
        self,
        user_id: str,
        query_vector: list[float],
        query_text: str,
        limit: int,
        rrf_k: int,
        candidate_multiplier: int,
    ) -> list[RecallRow]:
        """Full hybrid CTE: pgvector + FTS + RRF."""
        candidate_limit = limit * candidate_multiplier

        sql = text("""
            WITH vector_results AS (
                SELECT
                    p.id,
                    ROW_NUMBER() OVER (ORDER BY e.vector <=> :query_vector) AS rank
                FROM places p
                JOIN embeddings e ON e.place_id = p.id
                WHERE p.user_id = :user_id
                ORDER BY e.vector <=> :query_vector
                LIMIT :candidate_limit
            ),
            text_results AS (
                SELECT
                    p.id,
                    ROW_NUMBER() OVER (
                        ORDER BY
                            ts_rank(
                                to_tsvector(
                                    'english',
                                    p.place_name || ' ' || COALESCE(p.cuisine, '')
                                ),
                                plainto_tsquery('english', :query_text)
                            ) DESC
                    ) AS rank
                FROM places p
                WHERE p.user_id = :user_id
                  AND to_tsvector(
                      'english',
                      p.place_name || ' ' || COALESCE(p.cuisine, '')
                  ) @@ plainto_tsquery('english', :query_text)
            ),
            combined AS (
                SELECT
                    COALESCE(vr.id, tr.id) AS id,
                    COALESCE(1.0 / (:rrf_k + vr.rank), 0) +
                    COALESCE(1.0 / (:rrf_k + tr.rank), 0) AS rrf_score,
                    (vr.id IS NOT NULL) AS matched_vector,
                    (tr.id IS NOT NULL) AS matched_text
                FROM vector_results vr
                FULL OUTER JOIN text_results tr ON vr.id = tr.id
            )
            SELECT
                p.id AS place_id,
                p.place_name,
                p.address,
                p.cuisine,
                p.price_range,
                p.source_url,
                p.created_at AS saved_at,
                CASE
                    WHEN c.matched_vector AND c.matched_text
                        THEN 'Matched by name, cuisine, and semantic similarity'
                    WHEN c.matched_vector
                        THEN 'Matched by semantic similarity'
                    ELSE
                        'Matched by name or cuisine'
                END AS match_reason
            FROM combined c
            JOIN places p ON p.id = c.id
            ORDER BY c.rrf_score DESC
            LIMIT :limit
        """)

        result = await self._session.execute(
            sql,
            {
                "user_id": user_id,
                "query_vector": query_vector,
                "query_text": query_text,
                "limit": limit,
                "rrf_k": rrf_k,
                "candidate_limit": candidate_limit,
            },
        )

        rows = result.fetchall()
        return [
            RecallRow(
                place_id=row[0],
                place_name=row[1],
                address=row[2],
                cuisine=row[3],
                price_range=row[4],
                source_url=row[5],
                saved_at=row[6],
                match_reason=row[7],
            )
            for row in rows
        ]

    async def _text_only_search(
        self, user_id: str, query_text: str, limit: int
    ) -> list[RecallRow]:
        """Text-only search fallback (embedding failed)."""
        sql = text("""
            SELECT
                p.id AS place_id,
                p.place_name,
                p.address,
                p.cuisine,
                p.price_range,
                p.source_url,
                p.created_at AS saved_at,
                'Matched by name or cuisine (semantic unavailable)' AS match_reason
            FROM places p
            WHERE p.user_id = :user_id
              AND to_tsvector('english', p.place_name || ' ' || COALESCE(p.cuisine, ''))
                  @@ plainto_tsquery('english', :query_text)
            ORDER BY
                ts_rank(
                    to_tsvector('english', p.place_name || ' ' || COALESCE(p.cuisine, '')),
                    plainto_tsquery('english', :query_text)
                ) DESC
            LIMIT :limit
        """)

        result = await self._session.execute(
            sql,
            {
                "user_id": user_id,
                "query_text": query_text,
                "limit": limit,
            },
        )

        rows = result.fetchall()
        return [
            RecallRow(
                place_id=row[0],
                place_name=row[1],
                address=row[2],
                cuisine=row[3],
                price_range=row[4],
                source_url=row[5],
                saved_at=row[6],
                match_reason=row[7],
            )
            for row in rows
        ]
