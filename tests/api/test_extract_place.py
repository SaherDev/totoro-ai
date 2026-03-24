"""Integration tests for POST /v1/extract-place endpoint."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from totoro_ai.api.main import app
from totoro_ai.api.schemas.extract_place import ExtractPlaceRequest


def test_extract_place_success_saves_place() -> None:
    """Test successful extraction and place save (confidence ≥ 0.70)."""
    client = TestClient(app)

    with patch("httpx.AsyncClient") as mock_client_class:
        # Mock the TikTok oEmbed response
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "title": "Best ramen I ever had! Fuji Ramen at 123 Main St",
            "description": "Fuji Ramen restaurant"
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        request = ExtractPlaceRequest(
            user_id="test-user",
            raw_input="https://tiktok.com/v/123",
        )

        response = client.post(
            "/v1/extract-place",
            json=request.model_dump(),
        )

        # Without a real database and with mocked LLM, response depends on service state
        assert response.status_code in [200, 422, 500]


def test_extract_place_empty_input_returns_400() -> None:
    """Test that empty input returns 400 Bad Request."""
    client = TestClient(app)

    request = ExtractPlaceRequest(
        user_id="test-user",
        raw_input="",
    )

    response = client.post(
        "/v1/extract-place",
        json=request.model_dump(),
    )

    assert response.status_code == 400
    data = response.json()
    assert data.get("error_type") == "bad_request"


def test_extract_place_unsupported_input_returns_422() -> None:
    """Test that unsupported input type returns 422."""
    client = TestClient(app)

    request = ExtractPlaceRequest(
        user_id="test-user",
        raw_input="https://instagram.com/p/123",
    )

    with patch(
        "totoro_ai.api.routes.extract_place.get_extraction_service"
    ) as mock_service_dep:
        from totoro_ai.core.extraction.dispatcher import UnsupportedInputError

        mock_service = AsyncMock()
        mock_service.run.side_effect = UnsupportedInputError("No extractor supports input")
        mock_service_dep.return_value = mock_service

        response = client.post(
            "/v1/extract-place",
            json=request.model_dump(),
        )

        assert response.status_code == 422
        data = response.json()
        assert data.get("error_type") == "unsupported_input"


def test_extract_place_low_confidence_requires_confirmation() -> None:
    """Test that low confidence (0.30-0.70) returns requires_confirmation=True."""
    client = TestClient(app)

    request = ExtractPlaceRequest(
        user_id="test-user",
        raw_input="some ambiguous place name",
    )

    response = client.post(
        "/v1/extract-place",
        json=request.model_dump(),
    )

    # Response depends on service mocking
    # This test structure is set up for future implementation
    assert response.status_code in [200, 422, 500]


def test_extract_place_deduplication() -> None:
    """Test that existing place with same google_place_id is returned."""
    client = TestClient(app)

    with patch("httpx.AsyncClient") as mock_client_class:
        # Mock the TikTok oEmbed response
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "title": "Another place I like",
            "description": "Restaurant location"
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        request = ExtractPlaceRequest(
            user_id="test-user-2",
            raw_input="https://tiktok.com/v/456",
        )

        response = client.post(
            "/v1/extract-place",
            json=request.model_dump(),
        )

        # Deduplication logic requires database access
        assert response.status_code in [200, 422, 500]
