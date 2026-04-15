"""Tests for intent extraction and parsing.

`ParsedIntent` is the minimal-intent shape — only the fields that drive
dispatch decisions live on it. Attribute-level signals (cuisine, price,
ambiance, dietary, occasion) travel inside `enriched_query` as text.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from totoro_ai.core.intent.intent_parser import IntentParser, ParsedIntent
from totoro_ai.core.places.models import PlaceType


async def test_parse_returns_parsed_intent() -> None:
    """parse() returns a ParsedIntent with the LLM-extracted shape."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place_type=PlaceType.food_and_drink,
            enriched_query="ramen for date night",
            discovery_filters={"type": "restaurant"},
        )

        parser = IntentParser()
        result = await parser.parse("good ramen for a date night")

        assert isinstance(result, ParsedIntent)
        assert result.place_type == PlaceType.food_and_drink
        assert result.enriched_query == "ramen for date night"
        assert result.discovery_filters == {"type": "restaurant"}


async def test_parse_returns_null_for_missing_fields() -> None:
    """parse() returns None/{} for fields not mentioned."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place_type=PlaceType.food_and_drink,
            enriched_query="pizza restaurants",
            discovery_filters={"type": "restaurant"},
        )

        parser = IntentParser()
        result = await parser.parse("pizza restaurants")

        assert result.radius_m is None
        assert result.search_location_name is None
        assert result.search_location is None


async def test_parse_enriched_query_falls_back_to_raw_when_empty() -> None:
    """If LLM returns empty enriched_query, fall back to the raw query string."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            enriched_query="",
            discovery_filters={},
        )

        parser = IntentParser()
        result = await parser.parse("find me something")

        assert result.enriched_query == "find me something"


async def test_parse_search_location_always_none() -> None:
    """parse() never resolves coordinates — search_location is always None."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            search_location_name=None,
            enriched_query="pizza restaurants",
            discovery_filters={"type": "restaurant"},
            search_location={"lat": 1.0, "lng": 2.0},  # ignored
        )

        parser = IntentParser()
        result = await parser.parse("pizza restaurants")

        assert result.search_location is None


async def test_parse_passes_through_search_location_name() -> None:
    """LLM-extracted location name appears in ParsedIntent; coords stay None."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            search_location_name="Asok",
            enriched_query="bar near Asok",
            discovery_filters={"type": "bar"},
        )

        parser = IntentParser()
        result = await parser.parse("bar near Asok")

        assert result.search_location_name == "Asok"
        assert result.search_location is None


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


async def test_parsed_intent_rejects_attribute_fields() -> None:
    """`extra='forbid'` guards against legacy cuisine/price_hint/etc. slipping back."""
    with pytest.raises(ValidationError):
        ParsedIntent(  # type: ignore[call-arg]
            place_type=PlaceType.food_and_drink,
            cuisine="japanese",
            enriched_query="ramen",
        )


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
            place_type=PlaceType.food_and_drink,
            radius_m=500,
            enriched_query="cheap japanese ramen nearby",
            discovery_filters={"type": "restaurant"},
        )

        parser = IntentParser()
        result = await parser.parse("cheap ramen nearby")

        assert result.place_type == PlaceType.food_and_drink
        assert result.radius_m == 500
        assert "ramen" in result.enriched_query
        assert "cheap" in result.enriched_query
        assert result.discovery_filters == {"type": "restaurant"}


async def test_example_nice_dinner_sukhumvit_date() -> None:
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place_type=PlaceType.food_and_drink,
            search_location_name="Sukhumvit",
            enriched_query="upscale romantic dinner Sukhumvit date",
            discovery_filters={"type": "restaurant"},
        )

        parser = IntentParser()
        result = await parser.parse("nice dinner in Sukhumvit for a date")

        assert result.place_type == PlaceType.food_and_drink
        assert result.search_location_name == "Sukhumvit"
        assert "Sukhumvit" in result.enriched_query


async def test_example_solo_coffee() -> None:
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place_type=PlaceType.food_and_drink,
            enriched_query="cozy quiet cafe solo coffee",
            discovery_filters={"type": "cafe"},
        )

        parser = IntentParser()
        result = await parser.parse("somewhere relaxing for a solo coffee")

        assert result.place_type == PlaceType.food_and_drink
        assert "cafe" in result.enriched_query or "coffee" in result.enriched_query
        assert result.discovery_filters == {"type": "cafe"}


async def test_example_late_night_drinks() -> None:
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place_type=PlaceType.food_and_drink,
            enriched_query="late night bar drinks",
            discovery_filters={"type": "bar"},
        )

        parser = IntentParser()
        result = await parser.parse("late night drinks")

        assert "late" in result.enriched_query
        assert result.discovery_filters == {"type": "bar"}


async def test_example_halal_food_nearby() -> None:
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            place_type=PlaceType.food_and_drink,
            radius_m=500,
            enriched_query="halal restaurant nearby",
            discovery_filters={"type": "restaurant"},
        )

        parser = IntentParser()
        result = await parser.parse("halal food nearby")

        assert "halal" in result.enriched_query
        assert result.radius_m == 500
        assert result.place_type == PlaceType.food_and_drink
