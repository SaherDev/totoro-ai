"""Tests for intent extraction and parsing."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from totoro_ai.core.intent.intent_parser import (
    IntentParser,
    ParsedIntent,
    _IntentLLMOutput,
)


async def test_parse_returns_parsed_intent() -> None:
    """Test that parse() returns a ParsedIntent model."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = _IntentLLMOutput(
            occasion="date night",
            price_range=None,
            radius=None,
            discovery_filters={"type": "restaurant", "keyword": "ramen"},
        )

        parser = IntentParser()
        result = await parser.parse("good ramen for a date night")

        assert isinstance(result, ParsedIntent)
        assert result.discovery_filters == {"type": "restaurant", "keyword": "ramen"}
        assert result.occasion == "date night"


async def test_parse_extracts_discovery_filters_and_occasion() -> None:
    """Test parse() correctly extracts discovery_filters and occasion fields."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = _IntentLLMOutput(
            occasion="quick lunch",
            price_range="low",
            radius=800,
            discovery_filters={"type": "restaurant", "keyword": "sushi"},
        )

        parser = IntentParser()
        result = await parser.parse("cheap sushi near me for a quick lunch")

        assert result.discovery_filters == {"type": "restaurant", "keyword": "sushi"}
        assert result.occasion == "quick lunch"
        assert result.price_range == "low"
        assert result.radius == 800


async def test_parse_returns_null_for_missing_fields() -> None:
    """Test parse() returns None for fields not mentioned."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = _IntentLLMOutput(
            occasion=None,
            price_range=None,
            radius=None,
            discovery_filters={"type": "restaurant", "keyword": "pizza"},
        )

        parser = IntentParser()
        result = await parser.parse("pizza restaurants")

        assert result.discovery_filters == {"type": "restaurant", "keyword": "pizza"}
        assert result.occasion is None
        assert result.price_range is None
        assert result.radius is None


async def test_parse_extracts_discovery_filters_for_non_food_venues() -> None:
    """Test parse() extracts discovery_filters with type for non-food venues."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = _IntentLLMOutput(
            occasion="date night",
            price_range=None,
            radius=None,
            discovery_filters={"type": "night_club"},
        )

        parser = IntentParser()
        result = await parser.parse("good club near khaosan for a date night")

        assert result.discovery_filters == {"type": "night_club"}
        assert result.occasion == "date night"


async def test_parse_propagates_validation_error() -> None:
    """Test parse() propagates ValidationError on schema failures."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        try:
            _IntentLLMOutput(radius="invalid")  # type: ignore[arg-type]
        except ValidationError as e:
            mock_client.extract.side_effect = e

        parser = IntentParser()

        with pytest.raises(ValidationError):
            await parser.parse("invalid query")


async def test_parse_passes_through_search_location_name() -> None:
    """LLM-extracted location name appears in ParsedIntent; search_location stays None."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = _IntentLLMOutput(
            search_location_name="Asok",
            discovery_filters={"type": "bar"},
        )

        parser = IntentParser()
        result = await parser.parse("bar near Asok")

        assert result.search_location_name == "Asok"
        assert result.search_location is None


async def test_parse_search_location_always_none() -> None:
    """parse() never resolves coordinates — search_location is always None."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = _IntentLLMOutput(
            search_location_name=None,
            discovery_filters={"type": "restaurant"},
        )

        parser = IntentParser()
        result = await parser.parse("pizza restaurants")

        assert result.search_location is None
