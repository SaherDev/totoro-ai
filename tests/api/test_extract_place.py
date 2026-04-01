"""Integration tests for POST /v1/extract-place endpoint."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from totoro_ai.api.main import app
from totoro_ai.api.schemas.extract_place import ExtractPlaceRequest


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
    from totoro_ai.api.deps import get_extraction_service
    from totoro_ai.core.extraction.dispatcher import UnsupportedInputError

    mock_service = AsyncMock()
    mock_service.run.side_effect = UnsupportedInputError("No extractor supports input")

    app.dependency_overrides[get_extraction_service] = lambda: mock_service
    client = TestClient(app)

    try:
        response = client.post(
            "/v1/extract-place",
            json={"user_id": "test-user", "raw_input": "https://instagram.com/p/123"},
        )

        assert response.status_code == 422
        data = response.json()
        assert data.get("error_type") == "unsupported_input"
    finally:
        app.dependency_overrides.clear()


def test_extract_place_returns_multi_place_response() -> None:
    """Test that the endpoint returns the new multi-place response shape."""
    from totoro_ai.api.deps import get_extraction_service
    from totoro_ai.api.schemas.extract_place import (
        ExtractedPlaceSchema,
        ExtractPlaceResponse,
    )
    from totoro_ai.core.extraction.models import ExtractionLevel

    mock_response = ExtractPlaceResponse(
        places=[
            ExtractedPlaceSchema(
                place_id="uuid-1",
                place_name="Fuji Ramen",
                confidence=0.90,
                resolved_by=ExtractionLevel.EMOJI_REGEX,
                requires_confirmation=False,
                external_provider="google",
                external_id="ChIJxyz",
            ),
        ],
        source_url="https://tiktok.com/v/123",
    )

    mock_service = AsyncMock()
    mock_service.run.return_value = mock_response

    app.dependency_overrides[get_extraction_service] = lambda: mock_service
    client = TestClient(app)

    try:
        response = client.post(
            "/v1/extract-place",
            json={"user_id": "test-user", "raw_input": "https://tiktok.com/v/123"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "complete"
        assert len(data["places"]) == 1
        assert data["places"][0]["place_name"] == "Fuji Ramen"
    finally:
        app.dependency_overrides.clear()


def test_extract_place_provisional_response() -> None:
    """Test that the endpoint returns a provisional response for background work."""
    from totoro_ai.api.deps import get_extraction_service
    from totoro_ai.api.schemas.extract_place import ProvisionalResponse
    from totoro_ai.core.extraction.models import ExtractionLevel

    mock_response = ProvisionalResponse(
        pending_levels=[
            ExtractionLevel.SUBTITLE_CHECK,
            ExtractionLevel.WHISPER_AUDIO,
        ],
    )

    mock_service = AsyncMock()
    mock_service.run.return_value = mock_response

    app.dependency_overrides[get_extraction_service] = lambda: mock_service
    client = TestClient(app)

    try:
        response = client.post(
            "/v1/extract-place",
            json={"user_id": "test-user", "raw_input": "https://tiktok.com/v/123"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert len(data["pending_levels"]) == 2
    finally:
        app.dependency_overrides.clear()
