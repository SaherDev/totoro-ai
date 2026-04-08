"""Tests for GET /v1/extract-place/status/{request_id} endpoint (ADR-048)."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from totoro_ai.api.deps import get_status_repo
from totoro_ai.api.main import app
from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository


@pytest.fixture
def mock_status_repo() -> AsyncMock:
    return AsyncMock(spec=ExtractionStatusRepository)


@pytest.fixture
def client(mock_status_repo: AsyncMock) -> TestClient:
    app.dependency_overrides[get_status_repo] = lambda: mock_status_repo
    yield TestClient(app)  # type: ignore[misc]
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# US1 — core polling behavior
# ---------------------------------------------------------------------------


def test_status_returns_200_when_result_exists(
    client: TestClient, mock_status_repo: AsyncMock
) -> None:
    """When cache holds a result, endpoint returns it with HTTP 200."""
    payload = {
        "provisional": False,
        "places": [{"place_id": "p1", "place_name": "Ramen Hero"}],
        "pending_levels": [],
        "extraction_status": "saved",
        "source_url": None,
        "request_id": None,
    }
    mock_status_repo.read = AsyncMock(return_value=payload)

    response = client.get("/v1/extract-place/status/some-request-id")

    assert response.status_code == 200
    body = response.json()
    assert body["extraction_status"] == "saved"
    assert body["places"][0]["place_name"] == "Ramen Hero"


def test_status_returns_processing_when_key_absent(
    client: TestClient, mock_status_repo: AsyncMock
) -> None:
    """When cache has no key, endpoint returns processing with HTTP 200."""
    mock_status_repo.read = AsyncMock(return_value=None)

    response = client.get("/v1/extract-place/status/some-request-id")

    assert response.status_code == 200
    assert response.json() == {"extraction_status": "processing"}


def test_status_returns_failed_when_background_found_nothing(
    client: TestClient, mock_status_repo: AsyncMock
) -> None:
    """When cache holds failed status, endpoint returns it with HTTP 200."""
    mock_status_repo.read = AsyncMock(return_value={"extraction_status": "failed"})

    response = client.get("/v1/extract-place/status/some-request-id")

    assert response.status_code == 200
    assert response.json() == {"extraction_status": "failed"}


def test_status_delegates_to_status_repo(
    client: TestClient, mock_status_repo: AsyncMock
) -> None:
    """Route delegates read to status_repo with the correct request_id."""
    mock_status_repo.read = AsyncMock(return_value=None)

    client.get("/v1/extract-place/status/abc-123")

    mock_status_repo.read.assert_awaited_once_with("abc-123")


# ---------------------------------------------------------------------------
# US2 — graceful unknown / expired ID handling
# ---------------------------------------------------------------------------


def test_unknown_request_id_returns_processing(
    client: TestClient, mock_status_repo: AsyncMock
) -> None:
    """Any unknown request_id returns processing — no 404 or error."""
    mock_status_repo.read = AsyncMock(return_value=None)

    response = client.get(
        "/v1/extract-place/status/00000000-0000-0000-0000-000000000000"
    )

    assert response.status_code == 200
    assert response.json()["extraction_status"] == "processing"


def test_expired_request_id_treated_same_as_missing(
    client: TestClient, mock_status_repo: AsyncMock
) -> None:
    """Expired TTL keys return None from cache — treated as processing."""
    mock_status_repo.read = AsyncMock(return_value=None)

    response = client.get("/v1/extract-place/status/expired-id")

    assert response.status_code == 200
    assert response.json()["extraction_status"] == "processing"


def test_request_id_forwarded_verbatim_to_repo(
    client: TestClient, mock_status_repo: AsyncMock
) -> None:
    """The exact path parameter value is passed to status_repo.read unchanged."""
    mock_status_repo.read = AsyncMock(return_value=None)

    client.get("/v1/extract-place/status/my-special-id-xyz")

    mock_status_repo.read.assert_awaited_once_with("my-special-id-xyz")
