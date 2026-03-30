"""Recall service — orchestrate embedding + hybrid search."""

import logging

from totoro_ai.api.schemas.recall import RecallResponse, RecallResult
from totoro_ai.core.config import RecallConfig
from totoro_ai.db.repositories.recall_repository import RecallRepository
from totoro_ai.providers.embeddings import EmbedderProtocol

logger = logging.getLogger(__name__)


class RecallService:
    """Recall service orchestrating embedding + search + response."""

    def __init__(
        self,
        embedder: EmbedderProtocol,
        recall_repo: RecallRepository,
        config: RecallConfig,
    ) -> None:
        """Initialize recall service.

        Args:
            embedder: Embedding provider (Voyage or fallback)
            recall_repo: Recall repository with hybrid search
            config: Recall configuration (limits, RRF k, etc.)
        """
        self._embedder = embedder
        self._repo = recall_repo
        self._config = config

    async def run(self, query: str, user_id: str) -> RecallResponse:
        """Execute recall search.

        1. Check cold start (user has no saves) → return empty with empty_state=True
        2. Try to embed query; on failure, set embedding=None
        3. Call hybrid_search with vector or None (fallback to text-only)
        4. Construct response with results, total count, empty_state flag
        """
        # Check cold start
        saved_count = await self._repo.count_saved_places(user_id)
        if saved_count == 0:
            return RecallResponse(results=[], total=0, empty_state=True)

        # Try to embed query
        embedding = None
        try:
            vectors = await self._embedder.embed([query], input_type="query")
            embedding = vectors[0]
        except RuntimeError as e:
            logger.warning(
                "Embedding failed in recall; falling back to text-only search",
                extra={"user_id": user_id, "error": str(e)},
            )

        # Hybrid search (with or without vector)
        rows = await self._repo.hybrid_search(
            user_id=user_id,
            query_vector=embedding,
            query_text=query,
            limit=self._config.max_results,
            rrf_k=self._config.rrf_k,
            candidate_multiplier=self._config.candidate_multiplier,
            min_rrf_score=self._config.min_rrf_score,
            max_cosine_distance=self._config.max_cosine_distance,
        )

        # Construct response
        results = [
            RecallResult(
                place_id=row["place_id"],
                place_name=row["place_name"],
                address=row["address"],
                cuisine=row["cuisine"],
                price_range=row["price_range"],
                source_url=row["source_url"],
                saved_at=row["saved_at"],
                match_reason=row["match_reason"],
            )
            for row in rows
        ]

        return RecallResponse(results=results, total=len(results), empty_state=False)
