"""Tests for PlacesSearchService — warm path, cold path, stale refresh."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from totoro_ai.core.places_v2.models import (
    LocationContext,
    PlaceCore,
    PlaceObject,
    PlaceQuery,
)
from totoro_ai.core.places_v2.search_service import PlacesSearchService


def _make_service(
    repo: MagicMock | None = None,
    cache: MagicMock | None = None,
    client: MagicMock | None = None,
    dispatcher: MagicMock | None = None,
    db_min_hits: int = 3,
) -> PlacesSearchService:
    repo = repo or MagicMock(
        search=AsyncMock(return_value=[]),
        save_places=AsyncMock(return_value=[]),
        upsert_place=AsyncMock(),
        upsert_places=AsyncMock(return_value=[]),
        get_by_provider_ids=AsyncMock(return_value={}),
    )
    cache = cache or MagicMock(
        mget=AsyncMock(return_value={}),
        mset=AsyncMock(),
    )
    client = client or MagicMock(
        text_search=AsyncMock(return_value=[]),
    )
    dispatcher = dispatcher or MagicMock(emit_upserted=AsyncMock())
    return PlacesSearchService(
        repo=repo,
        cache=cache,
        client=client,
        event_dispatcher=dispatcher,
        db_min_hits=db_min_hits,
    )


def _core(pid: str, lat: float | None = 1.0) -> PlaceCore:
    return PlaceCore(
        id=pid,
        provider_id=f"google:{pid}",
        place_name=f"Place {pid}",
        location=(
            LocationContext(lat=lat, address="Test St") if lat is not None else None
        ),
    )


def _object(pid: str) -> PlaceObject:
    return PlaceObject(
        id=pid,
        provider_id=f"google:{pid}",
        place_name=f"Place {pid}",
        location=LocationContext(lat=1.0, address="Test St"),
        rating=4.5,
    )


class TestWarmPath:
    async def test_returns_db_hits_with_cache_overlay(self) -> None:
        cores = [_core("a"), _core("b"), _core("c")]
        cached_obj = _object("b")
        repo = MagicMock(
            search=AsyncMock(return_value=cores),
            save_places=AsyncMock(return_value=[]),
            upsert_place=AsyncMock(),
        )
        cache = MagicMock(
            mget=AsyncMock(return_value={"google:b": cached_obj}),
            mset=AsyncMock(),
        )
        client = MagicMock(text_search=AsyncMock(return_value=[]))

        svc = _make_service(repo=repo, cache=cache, client=client, db_min_hits=3)
        results = await svc.search(PlaceQuery(text="ramen"), limit=20)

        assert len(results) == 3
        # b should have live fields overlaid
        b_result = next(r for r in results if r.provider_id == "google:b")
        assert b_result.rating == 4.5
        # Google client not called (warm path)
        client.text_search.assert_not_awaited()

    async def test_below_min_hits_triggers_cold_path(self) -> None:
        cores = [_core("a")]  # 1 < db_min_hits=3
        new_objects = [_object("x"), _object("y")]
        persisted = [PlaceCore(id="x", provider_id="google:x", place_name="Place x")]
        repo = MagicMock(
            search=AsyncMock(return_value=cores),
            save_places=AsyncMock(return_value=persisted),
            upsert_place=AsyncMock(),
        )
        cache = MagicMock(
            mget=AsyncMock(return_value={}),
            mset=AsyncMock(),
        )
        client = MagicMock(text_search=AsyncMock(return_value=new_objects))
        dispatcher = MagicMock(emit_upserted=AsyncMock())

        svc = _make_service(
            repo=repo, cache=cache, client=client, dispatcher=dispatcher, db_min_hits=3
        )
        results = await svc.search(PlaceQuery(text="ramen"), limit=20)

        client.text_search.assert_awaited_once()
        cache.mset.assert_awaited_once_with(new_objects)
        repo.save_places.assert_awaited_once()
        # Single batch event emitted
        dispatcher.emit_upserted.assert_awaited_once()
        assert len(results) >= 1


class TestStaleRefresh:
    async def test_stale_rows_are_refreshed(self) -> None:
        stale_core = _core("stale", lat=None)  # stale: lat is None
        fresh_core = _core("fresh", lat=13.7)
        refreshed = PlaceCore(
            id="stale",
            provider_id="google:stale",
            place_name="Place stale",
            location=LocationContext(lat=13.7, address="Refreshed St"),
        )
        repo = MagicMock(
            search=AsyncMock(return_value=[stale_core, fresh_core, _core("c")]),
            save_places=AsyncMock(return_value=[]),
            upsert_place=AsyncMock(return_value=refreshed),
            upsert_places=AsyncMock(return_value=[refreshed]),
            get_by_provider_ids=AsyncMock(return_value={}),
        )
        cache = MagicMock(
            mget=AsyncMock(return_value={}),
            mset=AsyncMock(),
        )
        client = MagicMock(
            text_search=AsyncMock(return_value=[_object("stale")])
        )
        dispatcher = MagicMock(emit_upserted=AsyncMock())

        svc = _make_service(
            repo=repo, cache=cache, client=client, dispatcher=dispatcher, db_min_hits=3
        )
        await svc.search(PlaceQuery(text="ramen"), limit=20)

        repo.upsert_places.assert_awaited_once()
        dispatcher.emit_upserted.assert_awaited_once()


class TestGetByIds:
    async def test_delegates_to_cache_only(self) -> None:
        cached = {"google:a": _object("a")}
        cache = MagicMock(mget=AsyncMock(return_value=cached), mset=AsyncMock())
        svc = _make_service(cache=cache)

        result = await svc.get_by_ids(["google:a", "google:miss"])

        cache.mget.assert_awaited_once_with(["google:a", "google:miss"])
        assert "google:a" in result
        assert "google:miss" not in result

    async def test_empty_input(self) -> None:
        cache = MagicMock(mget=AsyncMock(return_value={}), mset=AsyncMock())
        svc = _make_service(cache=cache)

        result = await svc.get_by_ids([])
        assert result == {}
