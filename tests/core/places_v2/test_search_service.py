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
from totoro_ai.core.places_v2.tags import CuisineTag


def _make_service(
    repo: MagicMock | None = None,
    cache: MagicMock | None = None,
    client: MagicMock | None = None,
    upsert_service: MagicMock | None = None,
) -> PlacesSearchService:
    repo = repo or MagicMock(
        find=AsyncMock(return_value=[]),
        get_by_provider_ids=AsyncMock(return_value={}),
    )
    cache = cache or MagicMock(
        mget=AsyncMock(return_value={}),
        mset=AsyncMock(),
    )
    client = client or MagicMock(
        search=AsyncMock(return_value=[]),
        get_by_ids=AsyncMock(return_value=[]),
    )
    upsert_service = upsert_service or MagicMock(
        upsert_many=AsyncMock(return_value=[]),
    )
    return PlacesSearchService(
        repo=repo,
        cache=cache,
        client=client,
        upsert_service=upsert_service,
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


# ---------------------------------------------------------------------------
# Warm path
# ---------------------------------------------------------------------------

class TestWarmPath:
    async def test_returns_db_hits_with_cache_overlay(self) -> None:
        cores = [_core("a"), _core("b"), _core("c")]
        cached_obj = _object("b")
        repo = MagicMock(
            find=AsyncMock(return_value=cores),
            get_by_provider_ids=AsyncMock(return_value={}),
        )
        cache = MagicMock(mget=AsyncMock(return_value={"google:b": cached_obj}))
        client = MagicMock(
            search=AsyncMock(return_value=[]),
            get_by_ids=AsyncMock(return_value=[]),
        )

        svc = _make_service(repo=repo, cache=cache, client=client)
        results = await svc.find(PlaceQuery(), limit=20)

        assert len(results) == 3
        b_result = next(r for r in results if r.provider_id == "google:b")
        assert b_result.rating == 4.5
        # warm path — no Google call
        client.search.assert_not_awaited()


# ---------------------------------------------------------------------------
# Cold path (Google fallback)
# ---------------------------------------------------------------------------

class TestColdPath:
    async def test_falls_back_to_google_when_db_empty(self) -> None:
        google_result = _object("g1")
        repo = MagicMock(
            find=AsyncMock(return_value=[]),
            get_by_provider_ids=AsyncMock(return_value={}),
        )
        cache = MagicMock(mget=AsyncMock(return_value={}), mset=AsyncMock())
        client = MagicMock(
            search=AsyncMock(return_value=[google_result]),
            get_by_ids=AsyncMock(return_value=[]),
        )
        upsert = MagicMock(upsert_many=AsyncMock(return_value=[_core("g1")]))

        svc = _make_service(
            repo=repo, cache=cache, client=client, upsert_service=upsert
        )
        results = await svc.find(
            PlaceQuery(place_name="Thai restaurants Bangkok"), limit=5
        )

        client.search.assert_awaited_once()
        upsert.upsert_many.assert_awaited_once()
        cache.mset.assert_awaited_once()
        assert results == [google_result]

    async def test_passes_full_query_to_client_search(self) -> None:
        """Service passes the PlaceQuery unchanged — client owns routing."""
        repo = MagicMock(find=AsyncMock(return_value=[]))
        client = MagicMock(
            search=AsyncMock(return_value=[]),
            get_by_ids=AsyncMock(return_value=[]),
        )
        q = PlaceQuery(
            tags=[CuisineTag.thai],
            location=LocationContext(lat=13.7, lng=100.5, radius_m=500),
        )
        svc = _make_service(repo=repo, client=client)
        await svc.find(q, limit=10)

        client.search.assert_awaited_once()
        passed_query: PlaceQuery = client.search.call_args.args[0]
        assert passed_query is q

    async def test_empty_google_result_returns_empty(self) -> None:
        repo = MagicMock(find=AsyncMock(return_value=[]))
        client = MagicMock(
            search=AsyncMock(return_value=[]),
            get_by_ids=AsyncMock(return_value=[]),
        )
        svc = _make_service(repo=repo, client=client)
        results = await svc.find(PlaceQuery())

        assert results == []


# ---------------------------------------------------------------------------
# Stale-row handling in find()
# ---------------------------------------------------------------------------

class TestFindEnrichment:
    async def test_full_cache_hit_skips_provider(self) -> None:
        """When every DB hit is in cache, no provider call is made."""
        repo = MagicMock(
            find=AsyncMock(return_value=[_core("a"), _core("b")]),
            get_by_provider_ids=AsyncMock(return_value={}),
        )
        cache = MagicMock(
            mget=AsyncMock(
                return_value={
                    "google:a": _object("a"),
                    "google:b": _object("b"),
                }
            ),
            mset=AsyncMock(),
        )
        client = MagicMock(
            search=AsyncMock(return_value=[]),
            get_by_ids=AsyncMock(return_value=[]),
        )
        svc = _make_service(repo=repo, cache=cache, client=client)
        await svc.find(PlaceQuery(), limit=20)

        cache.mget.assert_awaited_once()
        client.get_by_ids.assert_not_awaited()
        cache.mset.assert_not_awaited()

    async def test_stale_row_falls_back_to_provider(self) -> None:
        """A stale row → cache miss → client.get_by_ids → upsert + mset."""
        stale = _core("stale", lat=None)
        fresh = _core("fresh")
        repo = MagicMock(
            find=AsyncMock(return_value=[stale, fresh]),
            get_by_provider_ids=AsyncMock(return_value={}),
        )
        cache = MagicMock(
            mget=AsyncMock(return_value={"google:fresh": _object("fresh")}),
            mset=AsyncMock(),
        )
        client = MagicMock(
            search=AsyncMock(return_value=[]),
            get_by_ids=AsyncMock(return_value=[_object("stale")]),
        )
        upsert = MagicMock(upsert_many=AsyncMock(return_value=[]))
        svc = _make_service(
            repo=repo, cache=cache, client=client, upsert_service=upsert
        )
        await svc.find(PlaceQuery(), limit=20)

        client.get_by_ids.assert_awaited_once_with(["google:stale"])
        upsert.upsert_many.assert_awaited_once()
        cache.mset.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_by_ids
# ---------------------------------------------------------------------------

class TestGetByIds:
    async def test_full_cache_hit_skips_provider(self) -> None:
        cached = {"google:a": _object("a"), "google:b": _object("b")}
        cache = MagicMock(mget=AsyncMock(return_value=cached), mset=AsyncMock())
        client = MagicMock(
            search=AsyncMock(return_value=[]),
            get_by_ids=AsyncMock(return_value=[]),
        )
        svc = _make_service(cache=cache, client=client)

        result = await svc.get_by_ids(["google:a", "google:b"])

        cache.mget.assert_awaited_once_with(["google:a", "google:b"])
        client.get_by_ids.assert_not_awaited()
        cache.mset.assert_not_awaited()
        assert set(result) == {"google:a", "google:b"}

    async def test_cache_miss_falls_back_to_provider(self) -> None:
        """Misses are fetched, upserted, cached, and merged with hits."""
        cached = {"google:a": _object("a")}
        fetched = _object("b")
        cache = MagicMock(mget=AsyncMock(return_value=cached), mset=AsyncMock())
        client = MagicMock(
            search=AsyncMock(return_value=[]),
            get_by_ids=AsyncMock(return_value=[fetched]),
        )
        upsert = MagicMock(upsert_many=AsyncMock(return_value=[]))
        svc = _make_service(cache=cache, client=client, upsert_service=upsert)

        result = await svc.get_by_ids(["google:a", "google:b"])

        client.get_by_ids.assert_awaited_once_with(["google:b"])
        upsert.upsert_many.assert_awaited_once()
        cache.mset.assert_awaited_once_with([fetched])
        assert result["google:a"].provider_id == "google:a"
        assert result["google:b"] is fetched

    async def test_unresolvable_id_absent_from_result(self) -> None:
        """Ids the provider can't resolve are simply omitted from the result."""
        cache = MagicMock(mget=AsyncMock(return_value={}), mset=AsyncMock())
        client = MagicMock(
            search=AsyncMock(return_value=[]),
            get_by_ids=AsyncMock(return_value=[]),
        )
        upsert = MagicMock(upsert_many=AsyncMock(return_value=[]))
        svc = _make_service(cache=cache, client=client, upsert_service=upsert)

        result = await svc.get_by_ids(["google:ghost"])

        client.get_by_ids.assert_awaited_once_with(["google:ghost"])
        upsert.upsert_many.assert_not_awaited()
        cache.mset.assert_not_awaited()
        assert result == {}

    async def test_empty_input(self) -> None:
        cache = MagicMock(mget=AsyncMock(return_value={}), mset=AsyncMock())
        client = MagicMock(get_by_ids=AsyncMock(return_value=[]))
        svc = _make_service(cache=cache, client=client)
        assert await svc.get_by_ids([]) == {}
        cache.mget.assert_not_awaited()
        client.get_by_ids.assert_not_awaited()
