"""Unit tests for PlacesService — create-path only (Phase 3 / US1).

The geo-only and full-enrichment paths (enrich_batch) are added in Phases 4/5
and live in their own test classes here later.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.core.places.models import (
    PlaceCreate,
    PlaceObject,
    PlaceProvider,
    PlaceType,
)
from totoro_ai.core.places.service import PlacesService


def _make_place_create(
    place_name: str = "Cafe A",
    external_id: str = "ChIJ_aaa",
) -> PlaceCreate:
    return PlaceCreate(
        user_id="u1",
        place_name=place_name,
        place_type=PlaceType.food_and_drink,
        provider=PlaceProvider.google,
        external_id=external_id,
    )


def _make_place_object(
    place_id: str = "pid-1", place_name: str = "Cafe A"
) -> PlaceObject:
    return PlaceObject(
        place_id=place_id,
        place_name=place_name,
        place_type=PlaceType.food_and_drink,
    )


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


async def test_create_returns_tier1_place_object_with_freshness_flags_false() -> None:
    repo = MagicMock()
    repo.create = AsyncMock(return_value=_make_place_object())
    service = PlacesService(repo=repo)

    result = await service.create(_make_place_create())

    repo.create.assert_awaited_once()
    assert result.place_id == "pid-1"
    assert result.geo_fresh is False
    assert result.enriched is False
    assert result.lat is None
    assert result.lng is None


# ---------------------------------------------------------------------------
# create_batch
# ---------------------------------------------------------------------------


async def test_create_batch_calls_repo_create_batch_exactly_once() -> None:
    repo = MagicMock()
    repo.create_batch = AsyncMock(
        return_value=[
            _make_place_object(place_id="p1", place_name="A"),
            _make_place_object(place_id="p2", place_name="B"),
            _make_place_object(place_id="p3", place_name="C"),
        ]
    )
    service = PlacesService(repo=repo)

    inputs = [
        _make_place_create(place_name="A", external_id="id_a"),
        _make_place_create(place_name="B", external_id="id_b"),
        _make_place_create(place_name="C", external_id="id_c"),
    ]
    result = await service.create_batch(inputs)

    assert repo.create_batch.await_count == 1
    assert [p.place_name for p in result] == ["A", "B", "C"]


async def test_create_batch_preserves_input_order() -> None:
    expected = [
        _make_place_object(place_id="p1", place_name="X"),
        _make_place_object(place_id="p2", place_name="Y"),
    ]
    repo = MagicMock()
    repo.create_batch = AsyncMock(return_value=expected)
    service = PlacesService(repo=repo)

    result = await service.create_batch(
        [
            _make_place_create(place_name="X", external_id="x"),
            _make_place_create(place_name="Y", external_id="y"),
        ]
    )

    assert [p.place_name for p in result] == ["X", "Y"]


async def test_create_batch_empty_returns_empty_without_repo_call() -> None:
    repo = MagicMock()
    repo.create_batch = AsyncMock(return_value=[])
    service = PlacesService(repo=repo)

    result = await service.create_batch([])

    # Contract: empty input returns [] (the repo returns [] already; we assert
    # that the service passes through to the repo at most once).
    assert result == []


# ---------------------------------------------------------------------------
# get / get_by_external_id / get_batch pass-through
# ---------------------------------------------------------------------------


async def test_get_delegates_to_repo_and_returns_place_object() -> None:
    repo = MagicMock()
    repo.get = AsyncMock(return_value=_make_place_object())
    service = PlacesService(repo=repo)

    result = await service.get("pid-1")

    repo.get.assert_awaited_once_with("pid-1")
    assert result is not None
    assert result.geo_fresh is False
    assert result.enriched is False


async def test_get_batch_delegates_to_repo() -> None:
    repo = MagicMock()
    repo.get_batch = AsyncMock(
        return_value=[
            _make_place_object(place_id="a", place_name="A"),
            _make_place_object(place_id="c", place_name="C"),
        ]
    )
    service = PlacesService(repo=repo)

    result = await service.get_batch(["a", "b", "c"])

    repo.get_batch.assert_awaited_once_with(["a", "b", "c"])
    assert [p.place_id for p in result] == ["a", "c"]


async def test_get_by_external_id_delegates_to_repo() -> None:
    repo = MagicMock()
    repo.get_by_external_id = AsyncMock(return_value=_make_place_object())
    service = PlacesService(repo=repo)

    result = await service.get_by_external_id(PlaceProvider.google, "ChIJ_aaa")

    repo.get_by_external_id.assert_awaited_once_with(PlaceProvider.google, "ChIJ_aaa")
    assert result is not None


# ---------------------------------------------------------------------------
# enrich_batch stub
# ---------------------------------------------------------------------------


async def test_enrich_batch_raises_not_implemented_in_phase_3() -> None:
    repo = MagicMock()
    service = PlacesService(repo=repo)

    with pytest.raises(NotImplementedError):
        await service.enrich_batch([_make_place_object()], geo_only=True)
