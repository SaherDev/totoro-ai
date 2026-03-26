"""Tests for intent extraction and parsing."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from totoro_ai.core.intent.intent_parser import IntentParser, ParsedIntent


@pytest.mark.asyncio
async def test_parse_returns_parsed_intent() -> None:
    """Test that parse() returns a ParsedIntent model."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        # Mock the instructor client to return a ParsedIntent
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            cuisine="ramen",
            occasion="date night",
            price_range=None,
            radius=None,
            constraints=[],
        )

        parser = IntentParser()
        result = await parser.parse("good ramen for a date night")

        assert isinstance(result, ParsedIntent)
        assert result.cuisine == "ramen"
        assert result.occasion == "date night"


@pytest.mark.asyncio
async def test_parse_extracts_cuisine_and_occasion() -> None:
    """Test parse() correctly extracts cuisine and occasion fields."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_client.extract.return_value = ParsedIntent(
            cuisine="sushi",
            occasion="quick lunch",
            price_range="low",
            radius=800,
            constraints=["vegetarian"],
        )

        parser = IntentParser()
        result = await parser.parse("cheap sushi near me for a quick lunch")

        assert result.cuisine == "sushi"
        assert result.occasion == "quick lunch"
        assert result.price_range == "low"
        assert result.radius == 800
        assert result.constraints == ["vegetarian"]


@pytest.mark.asyncio
async def test_parse_returns_null_for_missing_fields() -> None:
    """Test parse() returns None for fields not mentioned."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        # Only cuisine is specified, others are None
        mock_client.extract.return_value = ParsedIntent(
            cuisine="pizza",
            occasion=None,
            price_range=None,
            radius=None,
            constraints=[],
        )

        parser = IntentParser()
        result = await parser.parse("pizza restaurants")

        assert result.cuisine == "pizza"
        assert result.occasion is None
        assert result.price_range is None
        assert result.radius is None
        assert result.constraints == []


@pytest.mark.asyncio
async def test_parse_propagates_validation_error() -> None:
    """Test parse() propagates ValidationError on schema failures."""
    with patch(
        "totoro_ai.core.intent.intent_parser.get_instructor_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        # Create a ParsedIntent with invalid data to trigger ValidationError
        try:
            # This will raise ValidationError for invalid radius type
            ParsedIntent(cuisine="ramen", radius="invalid")  # type: ignore[arg-type]
        except ValidationError as e:
            mock_client.extract.side_effect = e

        parser = IntentParser()

        # Verify that ValidationError is propagated (not caught)
        with pytest.raises(ValidationError):
            await parser.parse("invalid query")
