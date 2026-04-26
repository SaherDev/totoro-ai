"""Tests for places_v2 domain models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from totoro_ai.core.places_v2.models import (
    LocationContext,
    PlaceAttributes,
    PlaceCore,
    PlaceCoreUpsertedEvent,
    PlaceObject,
    PlaceQuery,
    PlaceSource,
    SavedPlaceView,
    UserPlace,
)


class TestUserPlaceValidation:
    def test_url_required_for_tiktok(self) -> None:
        with pytest.raises(ValidationError, match="source_url is required"):
            UserPlace(
                user_place_id="up1",
                user_id="u1",
                place_id="p1",
                source=PlaceSource.tiktok,
                source_url=None,
                saved_at=datetime.now(UTC),
            )

    def test_url_forbidden_for_manual(self) -> None:
        with pytest.raises(ValidationError, match="source_url must be None"):
            UserPlace(
                user_place_id="up1",
                user_id="u1",
                place_id="p1",
                source=PlaceSource.manual,
                source_url="https://example.com",
                saved_at=datetime.now(UTC),
            )

    def test_url_forbidden_for_totoro(self) -> None:
        with pytest.raises(ValidationError, match="source_url must be None"):
            UserPlace(
                user_place_id="up1",
                user_id="u1",
                place_id="p1",
                source=PlaceSource.totoro,
                source_url="https://example.com",
                saved_at=datetime.now(UTC),
            )

    def test_valid_manual_source(self) -> None:
        up = UserPlace(
            user_place_id="up1",
            user_id="u1",
            place_id="p1",
            source=PlaceSource.manual,
            source_url=None,
            saved_at=datetime.now(UTC),
        )
        assert up.source == PlaceSource.manual
        assert up.source_url is None

    def test_valid_tiktok_source(self) -> None:
        up = UserPlace(
            user_place_id="up1",
            user_id="u1",
            place_id="p1",
            source=PlaceSource.tiktok,
            source_url="https://tiktok.com/v/123",
            saved_at=datetime.now(UTC),
        )
        assert up.source_url == "https://tiktok.com/v/123"

    def test_defaults(self) -> None:
        up = UserPlace(
            user_place_id="up1",
            user_id="u1",
            place_id="p1",
            source=PlaceSource.manual,
            saved_at=datetime.now(UTC),
        )
        assert up.needs_approval is False
        assert up.visited is False
        assert up.liked is None


class TestPlaceCore:
    def test_defaults(self) -> None:
        core = PlaceCore(place_name="Sukhumvit Joe's")
        assert core.tags == []
        assert core.id is None
        assert core.provider_id is None
        assert isinstance(core.attributes, PlaceAttributes)

    def test_full_construction(self) -> None:
        core = PlaceCore(
            id="abc",
            provider_id="google:ChIJ123",
            place_name="Sukhumvit Joe's",
            category="ramen",
            tags=["quiet", "solo-ok"],
            location=LocationContext(
                lat=13.756, lng=100.502, address="1 Sukhumvit, Bangkok"
            ),
        )
        assert core.provider_id == "google:ChIJ123"
        assert core.tags == ["quiet", "solo-ok"]


class TestPlaceObject:
    def test_extends_place_core(self) -> None:
        obj = PlaceObject(
            place_name="Test",
            provider_id="google:xyz",
            rating=4.5,
            popularity=1200,
        )
        assert obj.rating == 4.5
        assert obj.place_name == "Test"
        # Live fields default to None
        assert obj.hours is None
        assert obj.phone is None


class TestPlaceQuery:
    def test_all_optional(self) -> None:
        q = PlaceQuery()
        assert q.tags == []
        assert q.location is None

    def test_location_context_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            LocationContext(city="Bangkok", unknown_field="x")  # type: ignore[call-arg]


class TestSavedPlaceView:
    def test_construction(self) -> None:
        place = PlaceObject(place_name="Cafe X")
        up = UserPlace(
            user_place_id="u1",
            user_id="user",
            place_id="p1",
            source=PlaceSource.totoro,
            saved_at=datetime.now(UTC),
        )
        view = SavedPlaceView(place=place, user_data=up)
        assert view.place.place_name == "Cafe X"


class TestPlaceCoreUpsertedEvent:
    def test_construction(self) -> None:
        core = PlaceCore(place_name="Test")
        event = PlaceCoreUpsertedEvent(place_cores=[core])
        assert event.place_cores[0].place_name == "Test"
