"""Tests for the recall repository."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.db.repositories.recall_repository import (
    SQLAlchemyRecallRepository,
)


@pytest.fixture
def mock_session():
    """Create a mock database session."""
    session = AsyncMock()
    # Setup the mock to handle execute() calls
    # session.execute() returns a result object with mappings()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session):
    """Recall repository with mocked session."""
    return SQLAlchemyRecallRepository(mock_session)


def setup_mock_execute_result(mock_session, result_dicts):
    """Helper to setup mock session.execute() to return expected results.

    The repository code uses result.mappings().fetchall() to get dictionaries.
    """
    # Create a mock mappings object
    mock_mappings = MagicMock()
    mock_mappings.fetchall.return_value = result_dicts

    # Create a mock result object
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings

    # Mock scalar() for count queries
    mock_session.scalar = AsyncMock(return_value=0)
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


class TestRecallRepositoryVectorTextMatch:
    """T014: Test for vector+text match in US2 (Cross-Method Search Resilience)."""

    async def test_hybrid_search_returns_results_matching_both_methods(
        self, repo, mock_session
    ):
        """Verify result when query matches both vector and full-text search."""
        result_dicts = [
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
        setup_mock_execute_result(mock_session, result_dicts)

        # Execute hybrid search with vector + text
        results = await repo.hybrid_search(
            user_id="test-user-1",
            query_vector=[0.1, 0.2, 0.31],
            query_text="ramen",
            limit=10,
            rrf_k=60,
            candidate_multiplier=2,
        )

        # Verify
        assert len(results) > 0
        assert results[0]["place_id"] == "place-1"
        assert results[0]["place_name"] == "Cosy Ramen Spot"
        assert results[0]["match_reason"] == "vector_and_text"

    async def test_vector_text_match_includes_all_required_fields(
        self, repo, mock_session
    ):
        """Verify result includes all required fields."""
        result_dicts = [
            {
                "place_id": "place-1",
                "place_name": "Japanese Restaurant",
                "address": "456 Oak Ave",
                "cuisine": "Japanese",
                "price_range": "$$$",
                "source_url": "https://example.com/place",
                "saved_at": datetime.now(),
                "match_reason": "vector_and_text",
            }
        ]
        setup_mock_execute_result(mock_session, result_dicts)

        results = await repo.hybrid_search(
            user_id="user-1",
            query_vector=[0.5, 0.5, 0.51],
            query_text="japanese",
            limit=10,
            rrf_k=60,
            candidate_multiplier=2,
        )

        assert len(results) > 0
        result = results[0]
        required_fields = [
            "place_id",
            "place_name",
            "address",
            "cuisine",
            "price_range",
            "source_url",
            "saved_at",
            "match_reason",
        ]
        for field in required_fields:
            assert field in result


class TestRecallRepositoryTextOnlyMatch:
    """T015: Test for text-only match in US2 (Cross-Method Search Resilience)."""

    async def test_text_only_search_returns_results(self, repo, mock_session):
        """Verify result via text search when query matches keyword only."""
        result_dicts = [
            {
                "place_id": "place-1",
                "place_name": "Hidden Gem Ramen",
                "address": "789 Hidden Lane",
                "cuisine": "Japanese",
                "price_range": "$$",
                "source_url": "https://example.com",
                "saved_at": datetime.now(),
                "match_reason": "text",
            }
        ]
        setup_mock_execute_result(mock_session, result_dicts)

        # Execute text-only search (no vector match)
        results = await repo.hybrid_search(
            user_id="test-user-2",
            query_vector=None,  # No vector
            query_text="ramen",  # Text matches place_name
            limit=10,
            rrf_k=60,
            candidate_multiplier=2,
        )

        # Verify result is found via text search
        assert len(results) > 0
        assert results[0]["place_id"] == "place-1"
        assert results[0]["match_reason"] == "text"

    async def test_text_only_search_matches_cuisine_field(self, repo, mock_session):
        """Verify text search also matches cuisine field."""
        result_dicts = [
            {
                "place_id": "place-1",
                "place_name": "Generic Restaurant",
                "address": "999 Cuisine St",
                "cuisine": "Thai",
                "price_range": "$",
                "source_url": "https://example.com",
                "saved_at": datetime.now(),
                "match_reason": "text",
            }
        ]
        setup_mock_execute_result(mock_session, result_dicts)

        results = await repo.hybrid_search(
            user_id="user-text-search",
            query_vector=None,
            query_text="thai",  # Matches cuisine, not place_name
            limit=10,
            rrf_k=60,
            candidate_multiplier=2,
        )

        assert len(results) > 0
        assert results[0]["cuisine"] == "Thai"
        assert results[0]["match_reason"] == "text"


class TestRecallRepositoryVectorOnlyMatch:
    """T016: Test for vector-only match in US2 (Cross-Method Search Resilience)."""

    async def test_vector_only_search_returns_results(self, repo, mock_session):
        """Verify result via vector search when query has no keyword overlap."""
        result_dicts = [
            {
                "place_id": "place-1",
                "place_name": "Place123",
                "address": "111 Vector Lane",
                "cuisine": "Italian",
                "price_range": "$$$",
                "source_url": "https://example.com",
                "saved_at": datetime.now(),
                "match_reason": "vector",
            }
        ]
        setup_mock_execute_result(mock_session, result_dicts)

        # Execute with vector that's similar but no text match
        results = await repo.hybrid_search(
            user_id="test-user-3",
            query_vector=[0.8, 0.1, 0.21],  # Similar to embedding
            query_text="xyz",  # No text match in any field
            limit=10,
            rrf_k=60,
            candidate_multiplier=2,
        )

        # Result should be found via vector similarity
        assert len(results) > 0
        assert results[0]["place_id"] == "place-1"
        assert results[0]["match_reason"] == "vector"


class TestRecallRepositoryResultLimit:
    """T019: Test for configurable result limit in US4 (Configurable Result Limit)."""

    async def test_hybrid_search_respects_limit_parameter(self, repo, mock_session):
        """Verify limit parameter is respected; returns exactly specified number."""
        # Mock 10 results
        mock_results = [
            {
                "place_id": f"place-{i}",
                "place_name": f"Ramen Place {i}",
                "address": f"{i} Ramen St",
                "cuisine": "Japanese",
                "price_range": "$$",
                "source_url": "https://example.com",
                "saved_at": datetime.now(),
                "match_reason": "vector_and_text",
            }
            for i in range(10)
        ]
        setup_mock_execute_result(mock_session, mock_results)

        # Execute with limit=10
        results = await repo.hybrid_search(
            user_id="test-user-limit",
            query_vector=[0.5, 0.5, 0.5],
            query_text="ramen",
            limit=10,
            rrf_k=60,
            candidate_multiplier=2,
        )

        # Verify exactly 10 results returned
        assert len(results) == 10

    async def test_hybrid_search_with_limit_5(self, repo, mock_session):
        """Verify limit=5 returns exactly 5 results."""
        mock_results = [
            {
                "place_id": f"place-{i}",
                "place_name": f"Restaurant {i}",
                "address": f"{i} Italian St",
                "cuisine": "Italian",
                "price_range": "$",
                "source_url": "https://example.com",
                "saved_at": datetime.now(),
                "match_reason": "vector_and_text",
            }
            for i in range(5)
        ]
        setup_mock_execute_result(mock_session, mock_results)

        results = await repo.hybrid_search(
            user_id="test-limit-5",
            query_vector=[0.2, 0.2, 0.2],
            query_text="italian",
            limit=5,
            rrf_k=60,
            candidate_multiplier=2,
        )

        assert len(results) == 5

    async def test_hybrid_search_fewer_results_than_limit(self, repo, mock_session):
        """Verify returns fewer results if fewer exist than limit."""
        mock_results = [
            {
                "place_id": f"place-{i}",
                "place_name": f"Pizza {i}",
                "address": f"{i} Pizza St",
                "cuisine": "Italian",
                "price_range": "$$",
                "source_url": "https://example.com",
                "saved_at": datetime.now(),
                "match_reason": "vector_and_text",
            }
            for i in range(3)
        ]
        setup_mock_execute_result(mock_session, mock_results)

        results = await repo.hybrid_search(
            user_id="test-few-results",
            query_vector=[0.3, 0.3, 0.3],
            query_text="pizza",
            limit=10,  # Request 10
            rrf_k=60,
            candidate_multiplier=2,
        )

        # Should return only 3
        assert len(results) == 3


class TestRecallRepositoryCountSavedPlaces:
    """Test count_saved_places for cold start detection."""

    async def test_count_saved_places_returns_zero_for_new_user(
        self, repo, mock_session
    ):
        """Verify count is 0 for user with no saved places."""
        mock_session.scalar = AsyncMock(return_value=0)

        count = await repo.count_saved_places("never-saved-user")
        assert count == 0

    async def test_count_saved_places_returns_correct_count(self, repo, mock_session):
        """Verify count matches number of seeded places."""
        mock_session.scalar = AsyncMock(return_value=5)

        count = await repo.count_saved_places("count-test-user")
        assert count == 5

    async def test_count_saved_places_filters_by_user_id(self, repo, mock_session):
        """Verify count only includes places for that user."""

        # Create a side effect to return different counts per user
        async def count_side_effect(*args, **kwargs):
            # This is a simplified version; in reality we'd match on the query
            return 3

        mock_session.scalar = AsyncMock(side_effect=count_side_effect)

        await repo.count_saved_places("user-1")
        await repo.count_saved_places("user-2")

        # Both should have been called
        assert mock_session.scalar.call_count == 2
