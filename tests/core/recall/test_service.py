"""Tests for the recall service."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from totoro_ai.api.schemas.recall import RecallResponse
from totoro_ai.core.config import RecallConfig
from totoro_ai.core.recall.service import RecallService
from totoro_ai.providers.embeddings import EmbedderProtocol


@pytest.fixture
def recall_config():
    """RecallConfig fixture."""
    return RecallConfig(max_results=10, rrf_k=60, candidate_multiplier=2)


@pytest.fixture
def mock_embedder():
    """Mock embedder."""
    embedder = AsyncMock(spec=EmbedderProtocol)
    return embedder


@pytest.fixture
def mock_repo():
    """Mock recall repository."""
    repo = AsyncMock()
    return repo


@pytest.fixture
def recall_service(mock_embedder, mock_repo, recall_config):
    """RecallService instance with mocked dependencies."""
    return RecallService(
        embedder=mock_embedder,
        recall_repo=mock_repo,
        config=recall_config,
    )


class TestRecallServiceHappyPath:
    """T013: Service unit test for US1 (Natural Language Place Recall)."""

    async def test_run_with_successful_embedding_and_search(
        self, recall_service, mock_embedder, mock_repo
    ):
        """Verify service embeds query and returns search results with all fields."""
        # Setup mocks
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_repo.count_saved_places.return_value = 5
        mock_repo.hybrid_search.return_value = [
            {
                "place_id": "place-1",
                "place_name": "Cosy Ramen Spot",
                "address": "123 Main St",
                "cuisine": "Japanese",
                "price_range": "$$",
                "source_url": "https://example.com",
                "saved_at": datetime.now(),
                "match_reason": "vector_and_text",
            }
        ]

        # Execute
        response = await recall_service.run("cosy ramen spot", "test-user-1")

        # Assertions
        assert isinstance(response, RecallResponse)
        assert len(response.results) == 1
        assert response.results[0].place_id == "place-1"
        assert response.results[0].place_name == "Cosy Ramen Spot"
        assert response.results[0].match_reason in [
            "vector",
            "text",
            "vector_and_text",
        ]
        assert response.total == 1
        assert response.empty_state is False

        # Verify embedder was called with query input_type
        mock_embedder.embed.assert_called_once_with(
            ["cosy ramen spot"], input_type="query"
        )

    async def test_run_respects_result_limit_from_config(
        self, recall_service, mock_embedder, mock_repo, recall_config
    ):
        """Verify service passes configured limit to repository."""
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_repo.count_saved_places.return_value = 20
        mock_repo.hybrid_search.return_value = []

        await recall_service.run("test query", "test-user")

        # Verify hybrid_search was called with limit from config
        mock_repo.hybrid_search.assert_called_once()
        call_kwargs = mock_repo.hybrid_search.call_args[1]
        assert call_kwargs["limit"] == recall_config.max_results

    async def test_run_passes_rrf_k_to_repository(
        self, recall_service, mock_embedder, mock_repo
    ):
        """Verify service passes RRF k parameter to repository."""
        mock_embedder.embed.return_value = [[0.1]]
        mock_repo.count_saved_places.return_value = 5
        mock_repo.hybrid_search.return_value = []

        await recall_service.run("test", "user")

        # Verify rrf_k was passed
        call_kwargs = mock_repo.hybrid_search.call_args[1]
        assert call_kwargs["rrf_k"] == 60


class TestRecallServiceNoMatch:
    """T018: Service no-match test for US3 (Cold Start Empty State)."""

    async def test_run_no_match_with_saves_returns_results_empty(
        self, recall_service, mock_embedder, mock_repo
    ):
        """Verify user with saves but no match returns empty results, not error."""
        mock_embedder.embed.return_value = [[0.1, 0.2]]
        mock_repo.count_saved_places.return_value = 5
        mock_repo.hybrid_search.return_value = []

        response = await recall_service.run("obscure query", "test-user")

        assert response.results == []
        assert response.total == 0
        assert response.empty_state is False

    async def test_cold_start_returns_empty_state_true(
        self, recall_service, mock_embedder, mock_repo
    ):
        """Verify user with zero saves returns empty_state=true before embedding."""
        mock_repo.count_saved_places.return_value = 0

        response = await recall_service.run("any query", "new-user")

        assert response.results == []
        assert response.total == 0
        assert response.empty_state is True
        # Embedder should not be called on cold start
        mock_embedder.embed.assert_not_called()

    async def test_cold_start_skips_embedding_step(
        self, recall_service, mock_embedder, mock_repo
    ):
        """Verify cold start returns early without embedding."""
        mock_repo.count_saved_places.return_value = 0

        await recall_service.run("test", "user")

        # No embedding call should be made
        mock_embedder.embed.assert_not_called()
        # No search call should be made
        mock_repo.hybrid_search.assert_not_called()


class TestRecallServiceEmbeddingFailure:
    """T021: Embedding failure test for fallback handling."""

    async def test_embedding_failure_falls_back_to_text_only(
        self, recall_service, mock_embedder, mock_repo
    ):
        """Verify RuntimeError from embedder is caught and text-only search runs."""
        # Setup: embedder fails
        mock_embedder.embed.side_effect = RuntimeError("Embedding API timeout")
        mock_repo.count_saved_places.return_value = 3
        mock_repo.hybrid_search.return_value = [
            {
                "place_id": "place-1",
                "place_name": "Ramen Place",
                "address": "123 St",
                "cuisine": "Japanese",
                "price_range": "$$",
                "source_url": "https://example.com",
                "saved_at": datetime.now(),
                "match_reason": "text",
            }
        ]

        # Execute (should not raise)
        response = await recall_service.run("ramen", "test-user")

        # Verify: service still returns results via text search
        assert response.results
        assert response.results[0].match_reason == "text"
        assert response.empty_state is False

        # Verify: hybrid_search was called with query_vector=None
        mock_repo.hybrid_search.assert_called_once()
        call_kwargs = mock_repo.hybrid_search.call_args[1]
        assert call_kwargs["query_vector"] is None
        assert call_kwargs["query_text"] == "ramen"

    async def test_embedding_failure_does_not_raise_to_caller(
        self, recall_service, mock_embedder, mock_repo
    ):
        """Verify embedding failure is handled gracefully (no exception to caller)."""
        mock_embedder.embed.side_effect = RuntimeError("Network error")
        mock_repo.count_saved_places.return_value = 1
        mock_repo.hybrid_search.return_value = []

        # Should not raise
        response = await recall_service.run("query", "user")

        assert isinstance(response, RecallResponse)
        assert response.results == []

    async def test_embedding_failure_logs_warning(
        self, recall_service, mock_embedder, mock_repo, caplog
    ):
        """Verify embedding failure is logged with user_id context."""
        import logging

        caplog.set_level(logging.WARNING)
        mock_embedder.embed.side_effect = RuntimeError("API error")
        mock_repo.count_saved_places.return_value = 1
        mock_repo.hybrid_search.return_value = []

        await recall_service.run("test", "test-user-1")

        # Check that warning was logged (check caplog for the message)
        assert any(
            "Embedding failed" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )
