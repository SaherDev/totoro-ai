"""Tests for GooglePlacesClient — search routing and query-to-text translation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx

from totoro_ai.core.places_v2._google_query_builder import (
    build_text_search_params,
    query_to_google_text,
)
from totoro_ai.core.places_v2.google_client import GooglePlacesClient
from totoro_ai.core.places_v2.models import (
    LocationContext,
    PlaceCategory,
    PlaceQuery,
)
from totoro_ai.core.places_v2.tags import (
    AccessibilityTag,
    AtmosphereTag,
    CuisineTag,
    DietaryTag,
    FeatureTag,
    SeasonTag,
    ServiceTag,
    TimeTag,
)


def _make_client() -> GooglePlacesClient:
    client = GooglePlacesClient(
        api_key="test", http=MagicMock(spec=httpx.AsyncClient)
    )
    client.text_search = AsyncMock(return_value=[])
    client.nearby_search = AsyncMock(return_value=[])
    return client


# ---------------------------------------------------------------------------
# search() routing
# ---------------------------------------------------------------------------

class TestSearchRouting:
    async def test_category_routes_to_text_search(self) -> None:
        c = _make_client()
        await c.search(PlaceQuery(category=PlaceCategory.restaurant), limit=5)
        c.text_search.assert_awaited_once()
        c.nearby_search.assert_not_awaited()

    async def test_cuisine_tag_routes_to_text_search(self) -> None:
        c = _make_client()
        await c.search(PlaceQuery(place_name="Thai food"), limit=5)
        c.text_search.assert_awaited_once()
        c.nearby_search.assert_not_awaited()

    async def test_geo_only_routes_to_nearby_search(self) -> None:
        c = _make_client()
        await c.search(
            PlaceQuery(location=LocationContext(lat=13.7, lng=100.5, radius_m=500)),
            limit=5,
        )
        c.nearby_search.assert_awaited_once()
        c.text_search.assert_not_awaited()

    async def test_skip_tags_only_with_geo_falls_back_to_nearby(self) -> None:
        """Skip-only tags produce no text → falls back to nearby when geo present."""
        c = _make_client()
        await c.search(
            PlaceQuery(
                tags=[TimeTag.evening, AccessibilityTag.wheelchair_entrance],
                location=LocationContext(lat=13.7, lng=100.5, radius_m=500),
            ),
            limit=5,
        )
        c.nearby_search.assert_awaited_once()
        c.text_search.assert_not_awaited()

    async def test_skip_tags_no_geo_returns_empty(self) -> None:
        c = _make_client()
        result = await c.search(
            PlaceQuery(tags=[SeasonTag.summer, TimeTag.evening]), limit=5
        )
        assert result == []
        c.text_search.assert_not_awaited()
        c.nearby_search.assert_not_awaited()

    async def test_empty_query_returns_empty(self) -> None:
        c = _make_client()
        result = await c.search(PlaceQuery(), limit=5)
        assert result == []
        c.text_search.assert_not_awaited()
        c.nearby_search.assert_not_awaited()

    async def test_tags_with_geo_uses_text_search(self) -> None:
        """Searchable tags + geo → text_search (not nearby) so tags are applied."""
        c = _make_client()
        await c.search(
            PlaceQuery(
                tags=[CuisineTag.thai],
                location=LocationContext(lat=13.7, lng=100.5, radius_m=500),
            ),
            limit=5,
        )
        c.text_search.assert_awaited_once()
        passed_query: PlaceQuery = c.text_search.call_args.args[0]
        assert passed_query.location is not None
        c.nearby_search.assert_not_awaited()


# ---------------------------------------------------------------------------
# _query_to_google_text
# ---------------------------------------------------------------------------

class TestQueryToGoogleText:
    def test_place_name_is_first_part(self) -> None:
        q = PlaceQuery(place_name="ramen near Shibuya")
        assert query_to_google_text(q) == "ramen near Shibuya"

    def test_builds_from_category_and_tags(self) -> None:
        q = PlaceQuery(
            category=PlaceCategory.restaurant,
            tags=[CuisineTag.thai, FeatureTag.outdoor_seating],
        )
        text = query_to_google_text(q)
        assert "restaurant" in text
        assert "Thai" in text
        assert "outdoor seating" in text

    def test_underscores_converted_to_spaces(self) -> None:
        q = PlaceQuery(tags=[ServiceTag.serves_cocktails, AtmosphereTag.laid_back])
        text = query_to_google_text(q)
        assert "serves cocktails" in text
        assert "laid back" in text

    def test_time_tags_skipped(self) -> None:
        q = PlaceQuery(tags=[CuisineTag.japanese, TimeTag.evening])
        text = query_to_google_text(q)
        assert "Japanese" in text
        assert "evening" not in text

    def test_season_tags_skipped(self) -> None:
        q = PlaceQuery(tags=[DietaryTag.vegan, SeasonTag.summer])
        text = query_to_google_text(q)
        assert "vegan" in text
        assert "summer" not in text

    def test_accessibility_tags_skipped(self) -> None:
        q = PlaceQuery(tags=[CuisineTag.thai, AccessibilityTag.wheelchair_entrance])
        text = query_to_google_text(q)
        assert "Thai" in text
        assert "wheelchair" not in text

    def test_deduplicates_parts(self) -> None:
        q = PlaceQuery(place_name="Ramen", tags=["Ramen"])
        text = query_to_google_text(q)
        assert text.count("Ramen") == 1

    def test_empty_query_returns_empty_string(self) -> None:
        assert query_to_google_text(PlaceQuery()) == ""


# ---------------------------------------------------------------------------
# build_text_search_params — text/type dedup
# ---------------------------------------------------------------------------

class TestBuildTextSearchParams:
    def test_strips_type_mapped_tag_from_text_when_other_text_remains(self) -> None:
        q = PlaceQuery(place_name="ramen", tags=[CuisineTag.thai])
        text, included_type = build_text_search_params(q)
        assert text == "ramen"
        assert included_type == "thai_restaurant"

    def test_strips_type_mapped_category_from_text_when_other_text_remains(
        self,
    ) -> None:
        q = PlaceQuery(category=PlaceCategory.restaurant, tags=[DietaryTag.vegan])
        text, included_type = build_text_search_params(q)
        assert text == "vegan"
        assert included_type == "restaurant"

    def test_keeps_type_mapped_term_in_text_when_it_would_be_only_text(self) -> None:
        # Stripping would leave textQuery empty — Google rejects that.
        q = PlaceQuery(category=PlaceCategory.cafe)
        text, included_type = build_text_search_params(q)
        assert text == "cafe"
        assert included_type == "cafe"

    def test_keeps_type_mapped_tag_when_it_would_be_only_text(self) -> None:
        q = PlaceQuery(tags=[CuisineTag.thai])
        text, included_type = build_text_search_params(q)
        assert text == "Thai"
        assert included_type == "thai_restaurant"

    def test_category_takes_precedence_as_includedType(self) -> None:
        # Category checked before tags — its type wins the includedType slot.
        q = PlaceQuery(
            place_name="ramen",
            category=PlaceCategory.restaurant,
            tags=[CuisineTag.thai],
        )
        text, included_type = build_text_search_params(q)
        assert included_type == "restaurant"
        # Category is stripped; thai stays in text.
        assert "restaurant" not in text
        assert "Thai" in text
        assert "ramen" in text

    def test_unmapped_tag_falls_through_to_text(self) -> None:
        # FeatureTag has no entry in _TAG_TO_GOOGLE_TYPE — goes to text only.
        q = PlaceQuery(place_name="cafe", tags=[FeatureTag.outdoor_seating])
        text, included_type = build_text_search_params(q)
        assert included_type is None
        assert "cafe" in text
        assert "outdoor seating" in text

    def test_skip_tags_excluded_entirely(self) -> None:
        q = PlaceQuery(place_name="park", tags=[TimeTag.late_night])
        text, included_type = build_text_search_params(q)
        assert text == "park"
        assert included_type is None

    def test_empty_query_returns_empty_text_and_no_type(self) -> None:
        text, included_type = build_text_search_params(PlaceQuery())
        assert text == ""
        assert included_type is None
