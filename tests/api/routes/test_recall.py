"""Tests for the recall endpoint."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from totoro_ai.api.deps import get_recall_service
from totoro_ai.api.main import app
from totoro_ai.api.schemas.recall import RecallResponse, RecallResult
from totoro_ai.core.recall.service import RecallService


@pytest.fixture
def mock_recall_service():
    """Mock RecallService for dependency injection."""
    service = AsyncMock(spec=RecallService)
    return service


@pytest.fixture
def client(mock_recall_service):
    """FastAPI test client with mocked recall service."""
    # Override the dependency
    app.dependency_overrides[get_recall_service] = lambda: mock_recall_service
    yield TestClient(app)
    # Clean up
    app.dependency_overrides.clear()


class TestRecallRouteHappyPath:
    """T012: Happy-path route test for US1 (Natural Language Place Recall)."""

    def test_recall_returns_results_with_match_reason(
        self, client, mock_recall_service
    ):
        """Verify HTTP 200, results not empty, each has match_reason."""
        # Setup mock response
        mock_response = RecallResponse(
            results=[
                RecallResult(
                    place_id="place-1",
                    place_name="Cosy Ramen Spot",
                    address="123 Main St",
                    cuisine="Japanese",
                    price_range="$$",
                    source_url="https://example.com",
                    saved_at=datetime.now(),
                    match_reason="vector_and_text",
                )
            ],
            total=1,
            empty_state=False,
        )
        mock_recall_service.run.return_value = mock_response

        response = client.post(
            "/v1/recall",
            json={"query": "cosy ramen spot", "user_id": "test-user-1"},
        )

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) > 0
        assert data["total"] == len(data["results"])
        for result in data["results"]:
            assert "match_reason" in result
            assert result["match_reason"] in [
                "vector",
                "text",
                "vector_and_text",
            ]

    def test_recall_multiple_results(self, client, mock_recall_service):
        """Verify multiple results are returned with correct total count."""
        mock_response = RecallResponse(
            results=[
                RecallResult(
                    place_id=f"place-{i}",
                    place_name=f"Ramen Spot {i}",
                    address=f"{i} Main St",
                    cuisine="Japanese",
                    price_range="$$",
                    source_url="https://example.com",
                    saved_at=datetime.now(),
                    match_reason="vector_and_text",
                )
                for i in range(3)
            ],
            total=3,
            empty_state=False,
        )
        mock_recall_service.run.return_value = mock_response

        response = client.post(
            "/v1/recall",
            json={"query": "cosy ramen spot", "user_id": "test-user-1"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["results"]) == 3


class TestRecallColdStart:
    """T017: Cold start test for US3 (Cold Start Empty State)."""

    def test_cold_start_returns_empty_state(self, client, mock_recall_service):
        """Verify user with zero saves returns empty_state=true with empty results."""
        mock_response = RecallResponse(results=[], total=0, empty_state=True)
        mock_recall_service.run.return_value = mock_response

        response = client.post(
            "/v1/recall",
            json={"query": "any query", "user_id": "new-user"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        assert data["total"] == 0
        assert data["empty_state"] is True

    def test_cold_start_no_error_raised(self, client, mock_recall_service):
        """Verify HTTP 200 is returned (not 404, 422, or 500)."""
        mock_response = RecallResponse(results=[], total=0, empty_state=True)
        mock_recall_service.run.return_value = mock_response

        response = client.post(
            "/v1/recall",
            json={"query": "anything", "user_id": "never-saved"},
        )

        assert response.status_code == 200


class TestRecallValidation:
    """Test request validation."""

    def test_empty_query_returns_422(self):
        """Verify empty query is rejected by Pydantic."""
        client = TestClient(app)
        response = client.post(
            "/v1/recall",
            json={"query": "", "user_id": "test-user"},
        )
        assert response.status_code == 422

    def test_missing_query_returns_422(self):
        """Verify missing query field is rejected."""
        client = TestClient(app)
        response = client.post(
            "/v1/recall",
            json={"user_id": "test-user"},
        )
        assert response.status_code == 422

    def test_missing_user_id_returns_422(self):
        """Verify missing user_id field is rejected."""
        client = TestClient(app)
        response = client.post(
            "/v1/recall",
            json={"query": "test"},
        )
        assert response.status_code == 422
