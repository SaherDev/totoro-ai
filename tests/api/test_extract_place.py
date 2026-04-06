"""Integration tests for POST /v1/extract-place endpoint."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from totoro_ai.api.main import app
from totoro_ai.api.schemas.extract_place import (
    ExtractPlaceRequest,
    ExtractPlaceResponse,
)


def _mock_service_dep(mock_service: AsyncMock) -> None:
    """Override get_extraction_service with a mock service."""
    from totoro_ai.api import deps

    app.dependency_overrides[deps.get_extraction_service] = lambda: mock_service


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_extract_place_success_saves_place() -> None:
    """Test successful extraction returns 200 with saved places."""
    mock_service = AsyncMock()
    mock_service.run.return_value = ExtractPlaceResponse(
        provisional=False,
        places=[],
        pending_levels=[],
        extraction_status="saved",
        source_url="https://tiktok.com/v/123",
    )

    _mock_service_dep(mock_service)
    client = TestClient(app)

    try:
        request = ExtractPlaceRequest(
            user_id="test-user",
            raw_input="https://tiktok.com/v/123",
        )
        response = client.post("/v1/extract-place", json=request.model_dump())

        assert response.status_code == 200
        data = response.json()
        assert data["provisional"] is False
        assert data["extraction_status"] == "saved"
    finally:
        _clear_overrides()


def test_extract_place_empty_input_returns_400() -> None:
    """Test that empty input returns 400 Bad Request."""
    mock_service = AsyncMock()
    mock_service.run.side_effect = ValueError("raw_input cannot be empty")

    _mock_service_dep(mock_service)
    client = TestClient(app)

    try:
        request = ExtractPlaceRequest(
            user_id="test-user",
            raw_input="",
        )
        response = client.post("/v1/extract-place", json=request.model_dump())

        assert response.status_code == 400
        data = response.json()
        assert data.get("error_type") == "bad_request"
    finally:
        _clear_overrides()



def test_extract_place_provisional_response() -> None:
    """Test that provisional response returns processing status."""
    mock_service = AsyncMock()
    mock_service.run.return_value = ExtractPlaceResponse(
        provisional=True,
        places=[],
        pending_levels=["subtitle_check", "whisper_audio", "vision_frames"],
        extraction_status="processing",
        source_url="https://tiktok.com/v/456",
    )

    _mock_service_dep(mock_service)
    client = TestClient(app)

    try:
        request = ExtractPlaceRequest(
            user_id="test-user",
            raw_input="https://tiktok.com/v/456",
        )
        response = client.post("/v1/extract-place", json=request.model_dump())

        assert response.status_code == 200
        data = response.json()
        assert data["provisional"] is True
        assert data["extraction_status"] == "processing"
        assert len(data["pending_levels"]) == 3
    finally:
        _clear_overrides()


def test_extract_place_deduplication() -> None:
    """Test that all-duplicate result returns duplicate status with empty places."""
    mock_service = AsyncMock()
    mock_service.run.return_value = ExtractPlaceResponse(
        provisional=False,
        places=[],
        pending_levels=[],
        extraction_status="duplicate",
        source_url="https://tiktok.com/v/456",
    )

    _mock_service_dep(mock_service)
    client = TestClient(app)

    try:
        request = ExtractPlaceRequest(
            user_id="test-user-2",
            raw_input="https://tiktok.com/v/456",
        )
        response = client.post("/v1/extract-place", json=request.model_dump())

        assert response.status_code == 200
        data = response.json()
        assert data["extraction_status"] == "duplicate"
        assert data["places"] == []
    finally:
        _clear_overrides()
