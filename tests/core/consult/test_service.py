"""Unit tests for ConsultService tier-aware behavior (feature 023)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.api.schemas.consult import Location
from totoro_ai.api.schemas.recall import RecallResponse, RecallResult
from totoro_ai.core.consult.service import ConsultService
from totoro_ai.core.intent.intent_parser import (
    ParsedIntent,
    ParsedIntentPlace,
    ParsedIntentSearch,
)
from totoro_ai.core.places.models import (
    LocationContext,
    PlaceAttributes,
    PlaceObject,
    PlaceType,
)
from totoro_ai.core.taste.schemas import Chip, ChipStatus, TasteProfile


def _place(place_id: str, provider_id: str | None = None) -> PlaceObject:
    return PlaceObject(
        place_id=place_id,
        provider_id=provider_id or f"google:{place_id}",
        place_name=place_id,
        place_type=PlaceType.food_and_drink,
        subcategory="restaurant",
        tags=[],
        attributes=PlaceAttributes(location_context=LocationContext(city="Bangkok")),
        source=None,
        source_url=None,
        lat=13.75,
        lng=100.50,
        enriched=True,
    )


def _recall_result(place: PlaceObject) -> RecallResult:
    return RecallResult(place=place, match_reason="filter")


def _parsed_intent(lat: float = 13.75, lng: float = 100.5) -> ParsedIntent:
    return ParsedIntent(
        place=ParsedIntentPlace(
            place_type=PlaceType.food_and_drink,
            subcategory=None,
            tags=[],
            attributes=PlaceAttributes(),
        ),
        search=ParsedIntentSearch(
            radius_m=1500,
            search_location_name=None,
            search_location={"lat": lat, "lng": lng},
            enriched_query="Thai food",
            discovery_filters={},
        ),
    )


def _build_service(
    *,
    signal_count: int = 3,
    chips: list[Chip] | None = None,
    saved_places: list[PlaceObject] | None = None,
    discovered_places: list[PlaceObject] | None = None,
) -> tuple[ConsultService, dict[str, Any]]:
    saved_places = saved_places or []
    discovered_places = discovered_places or []

    intent_parser = AsyncMock()
    intent_parser.parse = AsyncMock(return_value=_parsed_intent())

    recall_service = AsyncMock()
    recall_service.run = AsyncMock(
        return_value=RecallResponse(
            results=[_recall_result(p) for p in saved_places],
            total_count=len(saved_places),
        )
    )

    places_client = AsyncMock()
    places_client.discover = AsyncMock(
        return_value=[
            {
                "place_id": p.place_id,
                "name": p.place_name,
                "types": ["restaurant"],
                "vicinity": "somewhere",
                "geometry": {"location": {"lat": p.lat, "lng": p.lng}},
                "_subcategory": p.subcategory,
            }
            for p in discovered_places
        ]
    )
    places_client.validate = AsyncMock(return_value=True)
    places_client.geocode = AsyncMock(return_value=None)

    places_service = AsyncMock()
    places_service.enrich_batch = AsyncMock(
        side_effect=lambda places, **_: list(places)
    )

    memory_service = AsyncMock()
    memory_service.load_memories = AsyncMock(return_value=[])

    taste_service = AsyncMock()
    profile = TasteProfile(
        taste_profile_summary=[],
        signal_counts={"totals": {"saves": signal_count}},
        chips=chips or [],
        generated_from_log_count=signal_count,
    )
    taste_service.get_taste_profile = AsyncMock(return_value=profile)

    recommendation_repo = MagicMock()
    recommendation_repo.save = AsyncMock(return_value="rec_id_stub")

    service = ConsultService(
        intent_parser=intent_parser,
        recall_service=recall_service,
        places_client=places_client,
        places_service=places_service,
        memory_service=memory_service,
        taste_service=taste_service,
        recommendation_repo=recommendation_repo,
    )
    return service, {
        "places_client": places_client,
        "recall_service": recall_service,
        "taste_service": taste_service,
    }


def _map_google_to_place_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub map_google_place_to_place_object to return the raw dict-wrapped object.

    The real mapper calls Google Places API mapping. For these tests we pre-build
    PlaceObjects and use a 1:1 stub.
    """
    from totoro_ai.core.consult import service as svc_module

    def _stub(raw: dict[str, Any]) -> PlaceObject:
        return PlaceObject(
            place_id=raw["place_id"],
            provider_id=f"google:{raw['place_id']}",
            place_name=raw["name"],
            place_type=PlaceType.food_and_drink,
            subcategory=raw.get("_subcategory", "restaurant"),
            tags=[],
            attributes=PlaceAttributes(
                location_context=LocationContext(city="Bangkok")
            ),
            source=None,
            source_url=None,
            lat=raw["geometry"]["location"]["lat"],
            lng=raw["geometry"]["location"]["lng"],
            enriched=True,
        )

    monkeypatch.setattr(svc_module, "map_google_place_to_place_object", _stub)


@pytest.mark.asyncio
async def test_warming_tier_applies_candidate_blend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _map_google_to_place_object(monkeypatch)

    saved_places = [_place(f"saved_{i}") for i in range(3)]
    discovered_places = [_place(f"disc_{i}") for i in range(5)]

    service, _ = _build_service(
        signal_count=3,  # below round_1=5 -> warming
        saved_places=saved_places,
        discovered_places=discovered_places,
    )

    response = await service.consult(
        user_id="warm_user",
        query="Thai food",
        location=Location(lat=13.75, lng=100.5),
        signal_tier="warming",
    )

    # total_cap=3, warming_blend 0.8/0.2 → saved_cap=1, discovered_cap=2.
    saved_in_results = [r for r in response.results if r.source == "saved"]
    discovered_in_results = [r for r in response.results if r.source == "discovered"]
    assert len(saved_in_results) == 1
    assert len(discovered_in_results) == 2

    blend_step = next(
        (s for s in response.reasoning_steps if s.step == "warming_blend"), None
    )
    assert blend_step is not None
    assert blend_step.summary == "discovered=2, saved=1"


@pytest.mark.asyncio
async def test_active_tier_excludes_rejected_chip_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _map_google_to_place_object(monkeypatch)

    # Two discovered candidates; one has subcategory=restaurant (should be dropped
    # by a rejected chip matching that subcategory) and one is a cafe.
    restaurant = PlaceObject(
        place_id="rest_1",
        provider_id="google:rest_1",
        place_name="A restaurant",
        place_type=PlaceType.food_and_drink,
        subcategory="restaurant",
        tags=[],
        attributes=PlaceAttributes(),
        source=None,
        source_url=None,
        lat=13.75,
        lng=100.5,
        enriched=True,
    )
    cafe = PlaceObject(
        place_id="cafe_1",
        provider_id="google:cafe_1",
        place_name="A cafe",
        place_type=PlaceType.food_and_drink,
        subcategory="cafe",
        tags=[],
        attributes=PlaceAttributes(),
        source=None,
        source_url=None,
        lat=13.75,
        lng=100.5,
        enriched=True,
    )

    rejected_chip = Chip(
        label="No restaurants",
        source_field="subcategory.food_and_drink",
        source_value="restaurant",
        signal_count=3,
        status=ChipStatus.REJECTED,
        selection_round="round_1",
    )

    service, _ = _build_service(
        signal_count=20,
        chips=[rejected_chip],
        saved_places=[],
        discovered_places=[restaurant, cafe],
    )

    response = await service.consult(
        user_id="active_user",
        query="food",
        location=Location(lat=13.75, lng=100.5),
        signal_tier="active",
    )

    place_ids = [r.place.place_id for r in response.results]
    assert "rest_1" not in place_ids
    assert "cafe_1" in place_ids

    filter_step = next(
        (s for s in response.reasoning_steps if s.step == "active_rejected_filter"),
        None,
    )
    assert filter_step is not None
    assert "1/" in filter_step.summary


@pytest.mark.asyncio
async def test_active_tier_surfaces_confirmed_chips_in_reasoning_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _map_google_to_place_object(monkeypatch)

    confirmed_chip = Chip(
        label="Ramen lover",
        source_field="attributes.cuisine",
        source_value="ramen",
        signal_count=5,
        status=ChipStatus.CONFIRMED,
        selection_round="round_1",
    )

    service, _ = _build_service(
        signal_count=20,
        chips=[confirmed_chip],
        saved_places=[_place("saved_1")],
        discovered_places=[_place("disc_1")],
    )

    response = await service.consult(
        user_id="active_user",
        query="Ramen nearby",
        location=Location(lat=13.75, lng=100.5),
        signal_tier="active",
    )

    step = next(
        (s for s in response.reasoning_steps if s.step == "active_confirmed_signals"),
        None,
    )
    assert step is not None
    assert "Ramen lover" in step.summary


@pytest.mark.asyncio
async def test_active_tier_does_not_add_warming_blend_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _map_google_to_place_object(monkeypatch)

    saved_places = [_place(f"saved_{i}") for i in range(2)]
    discovered_places = [_place(f"disc_{i}") for i in range(2)]

    chips = [
        Chip(
            label="Ramen",
            source_field="attributes.cuisine",
            source_value="ramen",
            signal_count=5,
            status=ChipStatus.CONFIRMED,
            selection_round="round_1",
        )
    ]

    service, _ = _build_service(
        signal_count=20,  # above round_1 and round_2, no actionable pending -> active
        chips=chips,
        saved_places=saved_places,
        discovered_places=discovered_places,
    )

    response = await service.consult(
        user_id="active_user",
        query="Ramen nearby",
        location=Location(lat=13.75, lng=100.5),
        signal_tier="active",
    )

    assert all(s.step != "warming_blend" for s in response.reasoning_steps)
