"""Tests for GoogleMapsListEnricher (Apify-backed)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from totoro_ai.core.extraction.enrichers.google_maps_list import (
    GoogleMapsListEnricher,
)
from totoro_ai.core.extraction.types import (
    ExtractionContext,
    ExtractionLevel,
)
from totoro_ai.core.places import PlaceProvider, PlaceSource


def _ctx(url: str = "https://maps.app.goo.gl/9KPNCHsoi5s69xE59") -> ExtractionContext:
    return ExtractionContext(url=url, user_id="u1")


def _mock_response(payload: object, status: int = 200) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    return response


class TestSourceGate:
    async def test_skips_when_source_is_not_google_maps(self) -> None:
        enricher = GoogleMapsListEnricher(token="t")
        ctx = ExtractionContext(url="https://tiktok.com/v/123", user_id="u1")
        with patch("httpx.AsyncClient") as client_cls:
            await enricher.enrich(ctx)
        client_cls.assert_not_called()
        assert ctx.candidates == []

    async def test_skips_when_no_url(self) -> None:
        enricher = GoogleMapsListEnricher(token="t")
        ctx = ExtractionContext(url=None, user_id="u1")
        with patch("httpx.AsyncClient") as client_cls:
            await enricher.enrich(ctx)
        client_cls.assert_not_called()


class TestTokenResolution:
    async def test_skips_silently_when_token_missing(self) -> None:
        enricher = GoogleMapsListEnricher(token=None)
        with (
            patch.object(enricher, "_resolve_token", return_value=None),
            patch("httpx.AsyncClient") as client_cls,
        ):
            await enricher.enrich(_ctx())
        client_cls.assert_not_called()


class TestApifyResponse:
    async def test_appends_candidate_per_item(self) -> None:
        enricher = GoogleMapsListEnricher(token="apify-token")
        items = [
            {"title": "Joe's Pizza", "placeId": "ChIJabc123"},
            {"title": "Eleven Madison Park", "placeId": "ChIJxyz789"},
        ]
        ctx = _ctx()

        async def _post(*_a, **_kw):  # type: ignore[no-untyped-def]
            return _mock_response(items)

        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.post = _post
            await enricher.enrich(ctx)

        assert len(ctx.candidates) == 2
        names = [c.place.place_name for c in ctx.candidates]
        assert names == ["Joe's Pizza", "Eleven Madison Park"]

    async def test_attaches_provider_and_external_id_from_place_id(self) -> None:
        enricher = GoogleMapsListEnricher(token="apify-token")
        items = [{"title": "Joe's Pizza", "placeId": "ChIJabc123"}]
        ctx = _ctx()

        async def _post(*_a, **_kw):  # type: ignore[no-untyped-def]
            return _mock_response(items)

        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.post = _post
            await enricher.enrich(ctx)

        cand = ctx.candidates[0]
        assert cand.place.provider == PlaceProvider.google
        assert cand.place.external_id == "ChIJabc123"
        assert cand.source is ExtractionLevel.GOOGLE_MAPS_LIST

    async def test_skips_items_without_a_name(self) -> None:
        enricher = GoogleMapsListEnricher(token="apify-token")
        items = [
            {"placeId": "ChIJnoname"},  # no title
            {"title": "Joe's Pizza", "placeId": "ChIJabc"},
        ]
        ctx = _ctx()

        async def _post(*_a, **_kw):  # type: ignore[no-untyped-def]
            return _mock_response(items)

        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.post = _post
            await enricher.enrich(ctx)

        assert len(ctx.candidates) == 1
        assert ctx.candidates[0].place.place_name == "Joe's Pizza"

    async def test_apify_http_error_propagates_to_circuit_breaker(self) -> None:
        """Errors must NOT be caught here — the surrounding CircuitBreakerEnricher
        owns the retry/back-off bookkeeping."""
        enricher = GoogleMapsListEnricher(token="apify-token")

        async def _post(*_a, **_kw):  # type: ignore[no-untyped-def]
            raise httpx.HTTPError("apify down")

        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.post = _post
            with pytest.raises(httpx.HTTPError):
                await enricher.enrich(_ctx())


class TestSourceGateMembership:
    def test_allowed_sources_is_google_maps_only(self) -> None:
        enricher = GoogleMapsListEnricher(token="t")
        assert enricher.allowed_sources == frozenset({PlaceSource.google_maps})
