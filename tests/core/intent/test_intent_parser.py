"""Tests for intent extraction and parsing.

`ParsedIntent` is the nested shape from ADR-056. `ParsedIntentPlace`
mirrors `PlaceObject` exactly, including nested `attributes: PlaceAttributes`
and `attributes.location_context`. The example tests mirror the prompt
examples inline in `intent_parser.py` — update them in lockstep.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from totoro_ai.core.intent.intent_parser import (
    IntentParser,
    ParsedIntent,
    ParsedIntentPlace,
    ParsedIntentSearch,
)
from totoro_ai.core.places.models import (
    LocationContext,
    PlaceAttributes,
    PlaceType,
)


async def test_parse_returns_parsed_intent_with_nested_groups() -> None:
    """parse() returns a ParsedIntent with .place and .search groups."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place=ParsedIntentPlace(
                place_type=PlaceType.food_and_drink,
                subcategory="restaurant",
                attributes=PlaceAttributes(
                    cuisine="japanese",
                    good_for=["date-night"],
                ),
            ),
            search=ParsedIntentSearch(
                enriched_query="romantic japanese date-night dinner",
                discovery_filters={"type": "restaurant"},
            ),
        )

        parser = IntentParser()
        result = await parser.parse("good ramen for a date night")

        assert isinstance(result, ParsedIntent)
        assert result.place.place_type == PlaceType.food_and_drink
        assert result.place.attributes.cuisine == "japanese"
        assert result.place.attributes.good_for == ["date-night"]
        assert result.search.discovery_filters == {"type": "restaurant"}


async def test_parse_returns_defaults_for_missing_fields() -> None:
    """parse() returns None/[] for fields not mentioned."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place=ParsedIntentPlace(
                place_type=PlaceType.food_and_drink,
                subcategory="restaurant",
            ),
            search=ParsedIntentSearch(
                enriched_query="pizza restaurants",
                discovery_filters={"type": "restaurant"},
            ),
        )

        parser = IntentParser()
        result = await parser.parse("pizza restaurants")

        assert result.place.attributes.price_hint is None
        assert result.place.attributes.ambiance is None
        assert result.place.attributes.good_for == []
        assert result.place.attributes.dietary == []
        assert result.place.attributes.location_context is None
        assert result.search.radius_m is None
        assert result.search.search_location_name is None


async def test_parse_enriched_query_falls_back_to_raw_when_empty() -> None:
    """If LLM returns empty enriched_query, fall back to the raw query string."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            search=ParsedIntentSearch(enriched_query=""),
        )

        parser = IntentParser()
        result = await parser.parse("find me something")

        assert result.search.enriched_query == "find me something"


async def test_parse_passes_through_search_location_name() -> None:
    """LLM-extracted location name appears in ParsedIntent; coords stay None."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            search=ParsedIntentSearch(
                search_location_name="Asok",
                enriched_query="bar near Asok",
                discovery_filters={"type": "bar"},
            ),
        )

        parser = IntentParser()
        result = await parser.parse("bar near Asok")

        assert result.search.search_location_name == "Asok"
        assert result.search.search_location is None


async def test_parse_propagates_exception() -> None:
    """parse() propagates extraction errors to the caller."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        mock_client.extract.side_effect = RuntimeError("llm exploded")

        parser = IntentParser()

        with pytest.raises(RuntimeError):
            await parser.parse("invalid query")


async def test_parsed_intent_forbids_extra_top_level_keys() -> None:
    """`extra='forbid'` guards against flat legacy fields slipping back in."""
    with pytest.raises(ValidationError):
        ParsedIntent(  # type: ignore[call-arg]
            place_type=PlaceType.food_and_drink,  # should live under .place
            cuisine="japanese",
        )


async def test_parsed_intent_place_forbids_flattened_attribute_keys() -> None:
    """Guards against attributes flattening back onto .place."""
    with pytest.raises(ValidationError):
        ParsedIntentPlace(  # type: ignore[call-arg]
            place_type=PlaceType.food_and_drink,
            cuisine="japanese",  # must live under place.attributes.cuisine
        )


def test_parsed_intent_search_location_is_excluded_from_schema() -> None:
    """ADR-056: search_location must be excluded from the LLM JSON schema.

    `Field(exclude=True)` omits the field from `model_dump()` output; a
    ParsedIntent serialized for the LLM never contains `search_location`,
    so the model cannot hallucinate coordinates into it.
    """
    dumped = ParsedIntent().model_dump()
    assert "search_location" not in dumped["search"]


# ---------------------------------------------------------------------------
# Prompt-example parity tests (one per example in the system prompt)
# ---------------------------------------------------------------------------


async def test_example_cheap_ramen_nearby() -> None:
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place=ParsedIntentPlace(
                place_type=PlaceType.food_and_drink,
                subcategory="restaurant",
                attributes=PlaceAttributes(
                    cuisine="japanese",
                    price_hint="cheap",
                ),
            ),
            search=ParsedIntentSearch(
                radius_m=500,
                enriched_query="cheap japanese ramen nearby",
                discovery_filters={"type": "restaurant"},
            ),
        )

        parser = IntentParser()
        result = await parser.parse("cheap ramen nearby")

        assert result.place.place_type == PlaceType.food_and_drink
        assert result.place.subcategory == "restaurant"
        assert result.place.attributes.cuisine == "japanese"
        assert result.place.attributes.price_hint == "cheap"
        assert result.search.radius_m == 500


async def test_example_nice_dinner_sukhumvit_date() -> None:
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place=ParsedIntentPlace(
                place_type=PlaceType.food_and_drink,
                attributes=PlaceAttributes(
                    price_hint="expensive",
                    good_for=["date-night"],
                    location_context=LocationContext(neighborhood="Sukhumvit"),
                ),
            ),
            search=ParsedIntentSearch(
                search_location_name="Sukhumvit",
                enriched_query="upscale romantic dinner Sukhumvit date",
                discovery_filters={"type": "restaurant"},
            ),
        )

        parser = IntentParser()
        result = await parser.parse("nice dinner in Sukhumvit for a date")

        assert result.place.attributes.price_hint == "expensive"
        assert result.place.attributes.good_for == ["date-night"]
        assert result.place.attributes.location_context is not None
        assert result.place.attributes.location_context.neighborhood == "Sukhumvit"
        assert result.search.search_location_name == "Sukhumvit"


async def test_example_quiet_museum_tokyo() -> None:
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place=ParsedIntentPlace(
                place_type=PlaceType.things_to_do,
                subcategory="museum",
                attributes=PlaceAttributes(
                    ambiance="quiet",
                    location_context=LocationContext(city="Tokyo"),
                ),
            ),
            search=ParsedIntentSearch(
                search_location_name="Tokyo",
                enriched_query="quiet museum Tokyo indoors rainy afternoon",
                discovery_filters={"type": "museum"},
            ),
        )

        parser = IntentParser()
        result = await parser.parse("quiet museum in Tokyo for a rainy afternoon")

        assert result.place.place_type == PlaceType.things_to_do
        assert result.place.subcategory == "museum"
        assert result.place.attributes.ambiance == "quiet"
        assert result.place.attributes.location_context is not None
        assert result.place.attributes.location_context.city == "Tokyo"


async def test_example_boutique_hotel_honeymoon() -> None:
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place=ParsedIntentPlace(
                place_type=PlaceType.accommodation,
                subcategory="hotel",
                tags=["boutique", "beach"],
                attributes=PlaceAttributes(
                    ambiance="romantic",
                    good_for=["honeymoon"],
                ),
            ),
            search=ParsedIntentSearch(
                enriched_query="boutique romantic beach hotel honeymoon",
                discovery_filters={"type": "lodging"},
            ),
        )

        parser = IntentParser()
        result = await parser.parse("boutique hotel near the beach for a honeymoon")

        assert result.place.place_type == PlaceType.accommodation
        assert result.place.subcategory == "hotel"
        assert "boutique" in result.place.tags
        assert result.place.attributes.good_for == ["honeymoon"]
        assert result.place.attributes.ambiance == "romantic"


async def test_example_cute_bookstore_shibuya() -> None:
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place=ParsedIntentPlace(
                place_type=PlaceType.shopping,
                subcategory="bookstore",
                attributes=PlaceAttributes(
                    ambiance="cozy",
                    location_context=LocationContext(neighborhood="Shibuya"),
                ),
            ),
            search=ParsedIntentSearch(
                search_location_name="Shibuya",
                enriched_query="cute cozy bookstore Shibuya",
                discovery_filters={"type": "book_store"},
            ),
        )

        parser = IntentParser()
        result = await parser.parse("cute bookstore in Shibuya")

        assert result.place.place_type == PlaceType.shopping
        assert result.place.subcategory == "bookstore"
        assert result.place.attributes.location_context is not None
        assert result.place.attributes.location_context.neighborhood == "Shibuya"
        assert result.search.search_location_name == "Shibuya"
