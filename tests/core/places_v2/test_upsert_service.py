"""Tests for PlaceUpsertService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.core.places_v2.models import PlaceCore, PlaceCoreUpsertedEvent
from totoro_ai.core.places_v2.upsert_service import PlaceUpsertService


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.upsert_place = AsyncMock()
    return repo


@pytest.fixture
def mock_dispatcher() -> MagicMock:
    dispatcher = MagicMock()
    dispatcher.emit_upserted = AsyncMock()
    return dispatcher


@pytest.fixture
def service(mock_repo: MagicMock, mock_dispatcher: MagicMock) -> PlaceUpsertService:
    return PlaceUpsertService(repo=mock_repo, event_dispatcher=mock_dispatcher)


class TestPlaceUpsertService:
    async def test_upsert_calls_repo_and_emits(
        self,
        service: PlaceUpsertService,
        mock_repo: MagicMock,
        mock_dispatcher: MagicMock,
    ) -> None:
        candidate = PlaceCore(place_name="Ramen Spot", provider_id="google:abc")
        persisted = PlaceCore(
            id="stored-id",
            place_name="Ramen Spot",
            provider_id="google:abc",
        )
        mock_repo.upsert_place.return_value = persisted

        result = await service.upsert(candidate)

        mock_repo.upsert_place.assert_awaited_once_with(candidate)
        mock_dispatcher.emit_upserted.assert_awaited_once()
        event: PlaceCoreUpsertedEvent = mock_dispatcher.emit_upserted.call_args.args[0]
        assert event.place_cores[0].id == "stored-id"
        assert result.id == "stored-id"

    async def test_returns_persisted_core(
        self,
        service: PlaceUpsertService,
        mock_repo: MagicMock,
        mock_dispatcher: MagicMock,
    ) -> None:
        persisted = PlaceCore(id="x", place_name="Test Place")
        mock_repo.upsert_place.return_value = persisted

        result = await service.upsert(PlaceCore(place_name="Test Place"))

        assert result is persisted
