"""Tests for DELETE /v1/user/{user_id}."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from totoro_ai.api.deps import get_user_deletion_service
from totoro_ai.api.routes.user import router as user_router
from totoro_ai.core.user.service import UserDeletionService


def _make_app(service: UserDeletionService) -> TestClient:
    app = FastAPI()
    app.include_router(user_router, prefix="/v1")
    app.dependency_overrides[get_user_deletion_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def svc() -> AsyncMock:
    service = AsyncMock(spec=UserDeletionService)
    service.delete_user = AsyncMock(return_value=None)
    return service


def test_delete_user_returns_204_with_empty_body(svc: AsyncMock) -> None:
    client = _make_app(svc)

    response = client.delete("/v1/user/user_abc")

    assert response.status_code == 204
    assert response.content == b""
    svc.delete_user.assert_awaited_once_with("user_abc")


def test_delete_user_idempotent_second_call_also_204(svc: AsyncMock) -> None:
    client = _make_app(svc)

    first = client.delete("/v1/user/user_abc")
    second = client.delete("/v1/user/user_abc")

    assert first.status_code == 204
    assert second.status_code == 204
    assert svc.delete_user.await_count == 2


def test_delete_user_service_exception_returns_500(svc: AsyncMock) -> None:
    """An unhandled service exception should surface as 500. We don't
    register the central error handler in this test app, so FastAPI's
    default 500 handler runs — same status code as production."""
    svc.delete_user.side_effect = RuntimeError("boom")
    client = _make_app(svc)

    response = client.delete("/v1/user/user_abc")

    assert response.status_code == 500


def test_delete_user_url_safe_user_ids(svc: AsyncMock) -> None:
    """Path-encoded characters should round-trip cleanly."""
    client = _make_app(svc)

    response = client.delete("/v1/user/user-with-dash_and_underscore.123")

    assert response.status_code == 204
    svc.delete_user.assert_awaited_once_with("user-with-dash_and_underscore.123")
