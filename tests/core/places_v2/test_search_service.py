"""Tests for PlacesSearchService — warm path, cold path, stale refresh."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from totoro_ai.core.places_v2.models import (
    LocationContext,
    PlaceCategory,
    PlaceCore,
    PlaceObject,
    PlaceQuery,
)
from totoro_ai.core.places_v2.search_service import (
    PlacesSearchService,
    _query_to_google_text,
)
from totoro_ai.core.places_v2.tags import (
    AtmosphereTag,
    CuisineTag,
    DietaryTag,
    FeatureTag,
    SeasonTag,
    ServiceTag,
    TimeTag,
)


def _make_service(
    repo: MagicMock | None = None,
    cache: MagicMock | None = None,
    client: MagicMock | None = None,
    dispatcher: MagicMock | None = None,
) -> PlacesSearchService:
    repo = repo or MagicMock(
        find=AsyncMock(return_value=[]),
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
        nearby_search=AsyncMock(return_value=[]),
    )
    dispatcher = dispatcher or MagicMock(emit_upserted=AsyncMock())
    return PlacesSearchService(
        repo=repo,
        cache=cache,
        client=client,
        event_dispatcher=dispatcher,
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
            upsert_places=AsyncMock(return_value=[]),
            get_by_provider_ids=AsyncMock(return_value={}),
        )
        cache = MagicMock(mget=AsyncMock(return_value={"google:b": cached_obj}))
        client = MagicMock(
            text_search=AsyncMock(return_value=[]),
            nearby_search=AsyncMock(return_value=[]),
        )

        svc = _make_service(repo=repo, cache=cache, client=client)
        results = await svc.find(PlaceQuery(), limit=20)

        assert len(results) == 3
        b_result = next(r for r in results if r.provider_id == "google:b")
        assert b_result.rating == 4.5
        client.text_search.assert_not_awaited()


# ---------------------------------------------------------------------------
# Cold path (Google fallback)
# ---------------------------------------------------------------------------

class TestColdPath:
    async def test_falls_back_to_google_when_db_empty(self) -> None:
        google_result = _object("g1")
        repo = MagicMock(
            find=AsyncMock(return_value=[]),
            save_places=AsyncMock(return_value=[_core("g1")]),
            upsert_places=AsyncMock(return_value=[]),
            get_by_provider_ids=AsyncMock(return_value={}),
        )
        cache = MagicMock(mget=AsyncMock(return_value={}), mset=AsyncMock())
        client = MagicMock(
            text_search=AsyncMock(return_value=[google_result]),
            nearby_search=AsyncMock(return_value=[]),
        )
        dispatcher = MagicMock(emit_upserted=AsyncMock())

        svc = _make_service(
            repo=repo, cache=cache, client=client, dispatcher=dispatcher
        )
        results = await svc.find(PlaceQuery(text="Thai restaurants Bangkok"), limit=5)

        client.text_search.assert_awaited_once()
        repo.save_places.assert_awaited_once()
        cache.mset.assert_awaited_once()
        dispatcher.emit_upserted.assert_awaited_once()
        assert results == [google_result]

    async def test_geo_only_uses_nearby_search(self) -> None:
        repo = MagicMock(
            find=AsyncMock(return_value=[]),
            save_places=AsyncMock(return_value=[]),
            upsert_places=AsyncMock(return_value=[]),
            get_by_provider_ids=AsyncMock(return_value={}),
        )
        cache = MagicMock(mget=AsyncMock(return_value={}), mset=AsyncMock())
        client = MagicMock(
            text_search=AsyncMock(return_value=[]),
            nearby_search=AsyncMock(return_value=[]),
        )

        svc = _make_service(repo=repo, cache=cache, client=client)
        # No tags, no text — only geo
        await svc.find(
            PlaceQuery(location=LocationContext(lat=13.7, lng=100.5, radius_m=500)),
        )

        client.nearby_search.assert_awaited_once()
        client.text_search.assert_not_awaited()

    async def test_text_with_geo_uses_text_search_with_location(self) -> None:
        repo = MagicMock(
            find=AsyncMock(return_value=[]),
            save_places=AsyncMock(return_value=[]),
            upsert_places=AsyncMock(return_value=[]),
            get_by_provider_ids=AsyncMock(return_value={}),
        )
        cache = MagicMock(mget=AsyncMock(return_value={}), mset=AsyncMock())
        client = MagicMock(
            text_search=AsyncMock(return_value=[]),
            nearby_search=AsyncMock(return_value=[]),
        )

        svc = _make_service(repo=repo, cache=cache, client=client)
        await svc.find(
            PlaceQuery(
                tags=[CuisineTag.thai],
                location=LocationContext(lat=13.7, lng=100.5, radius_m=500),
            ),
        )

        # Has tags → builds text → text_search with location, not nearby_search
        client.text_search.assert_awaited_once()
        call_kwargs = client.text_search.call_args
        assert call_kwargs.kwargs.get("location") is not None
        client.nearby_search.assert_not_awaited()

    async def test_no_text_no_geo_returns_empty(self) -> None:
        repo = MagicMock(find=AsyncMock(return_value=[]))
        client = MagicMock(
            text_search=AsyncMock(return_value=[]),
            nearby_search=AsyncMock(return_value=[]),
        )

        svc = _make_service(repo=repo, client=client)
        results = await svc.find(PlaceQuery())

        assert results == []
        client.text_search.assert_not_awaited()
        client.nearby_search.assert_not_awaited()


# ---------------------------------------------------------------------------
# _query_to_google_text
# ---------------------------------------------------------------------------

class TestQueryToGoogleText:
    def test_explicit_text_wins(self) -> None:
        q = PlaceQuery(text="ramen near Shibuya", category=PlaceCategory.restaurant)
        assert _query_to_google_text(q) == "ramen near Shibuya"

    def test_builds_from_category_and_tags(self) -> None:
        q = PlaceQuery(
            category=PlaceCategory.restaurant,
            tags=[CuisineTag.thai, FeatureTag.outdoor_seating],
        )
        text = _query_to_google_text(q)
        assert "restaurant" in text
        assert "Thai" in text
        assert "outdoor seating" in text

    def test_underscores_converted_to_spaces(self) -> None:
        q = PlaceQuery(tags=[ServiceTag.serves_cocktails, AtmosphereTag.laid_back])
        text = _query_to_google_text(q)
        assert "serves cocktails" in text
        assert "laid back" in text

    def test_time_tags_skipped(self) -> None:
        q = PlaceQuery(tags=[CuisineTag.japanese, TimeTag.evening])
        text = _query_to_google_text(q)
        assert "Japanese" in text
        assert "evening" not in text

    def test_season_tags_skipped(self) -> None:
        q = PlaceQuery(tags=[DietaryTag.vegan, SeasonTag.summer])
        text = _query_to_google_text(q)
        assert "vegan" in text
        assert "summer" not in text

    def test_deduplicates_parts(self) -> None:
        q = PlaceQuery(place_name="Ramen", tags=["Ramen"])
        text = _query_to_google_text(q)
        assert text.count("Ramen") == 1

    def test_empty_query_returns_empty_string(self) -> None:
        assert _query_to_google_text(PlaceQuery()) == ""


# ---------------------------------------------------------------------------
# Stale refresh
# ---------------------------------------------------------------------------

class TestStaleRefresh:
    async def test_stale_rows_are_refreshed(self) -> None:
        stale_core = _core("stale", lat=None)
        refreshed = PlaceCore(
            id="stale",
            provider_id="google:stale",
            place_name="Place stale",
            location=LocationContext(lat=13.7, address="Refreshed St"),
        )
        repo = MagicMock(
            find=AsyncMock(return_value=[stale_core, _core("c")]),
            save_places=AsyncMock(return_value=[]),
            upsert_place=AsyncMock(return_value=refreshed),
            upsert_places=AsyncMock(return_value=[refreshed]),
            get_by_provider_ids=AsyncMock(return_value={}),
        )
        cache = MagicMock(mget=AsyncMock(return_value={}), mset=AsyncMock())
        client = MagicMock(
            text_search=AsyncMock(return_value=[_object("stale")]),
            nearby_search=AsyncMock(return_value=[]),
        )
        dispatcher = MagicMock(emit_upserted=AsyncMock())

        svc = _make_service(
            repo=repo, cache=cache, client=client, dispatcher=dispatcher
        )
        await svc.find(PlaceQuery(), limit=20)

        repo.upsert_places.assert_awaited_once()
        dispatcher.emit_upserted.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_by_ids
# ---------------------------------------------------------------------------

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
        assert await svc.get_by_ids([]) == {}
