"""Intent extraction from natural language queries using Instructor."""

from typing import cast

from pydantic import BaseModel

from totoro_ai.providers import get_instructor_client, get_langfuse_client


class ParsedIntent(BaseModel):
    """Structured representation of user intent extracted from a query."""

    cuisine: str | None = None
    """Cuisine type (e.g., 'ramen', 'sushi'), or None if not specified."""

    occasion: str | None = None
    """Context/occasion (e.g., 'date night', 'quick lunch'), or None if
    not specified."""

    price_range: str | None = None
    """Price range preference ('low', 'mid', 'high'), or None if not
    specified."""

    radius: int | None = None
    """Preferred search radius in meters, or None if not specified."""

    constraints: list[str] = []
    """Dietary, access, or other requirements (empty list if none)."""


class IntentParser:
    """Extract structured intent from natural language place recommendation queries."""

    def __init__(self) -> None:
        """Initialize IntentParser with Instructor client for schema extraction."""
        self._client = get_instructor_client("intent_parser")

    async def parse(self, query: str) -> ParsedIntent:
        """Extract structured intent from a raw natural language query.

        Uses GPT-4o-mini via Instructor for reliable structured extraction.
        Pydantic validation automatically enforces schema constraints.

        Args:
            query: Raw natural language query from user

        Returns:
            ParsedIntent with extracted fields (null if not mentioned)

        Raises:
            ValidationError: If LLM response fails Pydantic validation
                (FastAPI returns 422 to caller)
        """
        lf = get_langfuse_client()

        system_prompt = (
            "You are an intent extraction assistant. Extract structured "
            "intent from a restaurant or place recommendation query. "
            "Return null for fields not mentioned."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        generation = None
        if lf:
            generation = lf.generation(
                name="intent_parsing",
                input={"system": system_prompt, "user": query},
            )

        try:
            # Instructor.extract() validates against schema
            # Raises ValidationError if response doesn't match
            # (propagates to FastAPI as 422)
            result = cast(
                ParsedIntent,
                await self._client.extract(
                    ParsedIntent,
                    messages=messages,
                ),
            )

            if generation:
                generation.end(output=result.model_dump())

            return result
        except Exception:
            if generation:
                generation.end(error=str(Exception))
            raise
