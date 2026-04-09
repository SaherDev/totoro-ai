"""Intent extraction from natural language queries using Instructor."""

from typing import Any, cast

from pydantic import BaseModel

from totoro_ai.providers import get_instructor_client, get_langfuse_client


class ParsedIntent(BaseModel):
    """Structured representation of user intent extracted from a query."""

    occasion: str | None = None
    """Context/occasion (e.g., 'date night', 'quick lunch'), or None if
    not specified."""

    price_range: str | None = None
    """Price range preference ('low', 'mid', 'high'), or None if not
    specified."""

    radius: int | None = None
    """Preferred search radius in meters (inferred from proximity signals like
    'nearby', 'walking distance'). LLM returns null when no radius signal
    detected; falls back to config default."""

    constraints: list[str] = []
    """Dietary, access, or other requirements (empty list if none)."""

    validate_candidates: bool = False
    """True if query signals validation is needed (e.g., 'open now', 'open tonight')."""

    discovery_filters: dict[str, Any] = {}
    """Filters to pass to PlacesClient.discover() (e.g., opennow, type, keyword)."""

    search_location: dict[str, float] | None = None
    """Resolved search location as {'lat': float, 'lng': float}, or None if
    no location signal and request location not provided. Resolution sources:
    - Request location (if provided)
    - Geocoded city/neighborhood (if query names a destination)
    - Geocoded street address (if query contains an address)
    """


class IntentParser:
    """Extract structured intent from natural language place recommendation queries."""

    def __init__(self) -> None:
        """Initialize IntentParser with Instructor client for schema extraction."""
        self._client = get_instructor_client("intent_parser")

    async def parse(
        self, query: str, location: dict[str, float] | None = None
    ) -> ParsedIntent:
        """Extract structured intent from a raw natural language query.

        Uses GPT-4o-mini via Instructor for reliable structured extraction.
        Resolves search_location from:
        1. Request location (if provided)
        2. Location signal in query (resolved via geocoding if present)
        3. None (if neither source available)

        Pydantic validation automatically enforces schema constraints.

        Args:
            query: Raw natural language query from user
            location: Optional location dict from request
                {'lat': float, 'lng': float}

        Returns:
            ParsedIntent with extracted fields (null if not mentioned)

        Raises:
            ValidationError: If LLM response fails Pydantic validation
                (FastAPI returns 422 to caller)
        """
        lf = get_langfuse_client()

        from totoro_ai.core.config import get_config

        config = get_config()
        radius_defaults = config.consult.radius_defaults

        system_prompt = (
            "You are an intent extraction assistant. Extract structured "
            "intent from place recommendation queries.\n"
            "\n"
            "Extract: occasion (e.g., date night), price_range (low/mid/high), radius "
            "in metres, and discovery_filters for Google Places API.\n"
            "\n"
            "Radius inference:\n"
            "- Detect proximity signals in any language: 'nearby', 'walking distance', "
            "'قريب مني' (close to me in Arabic), '附近' (nearby in Chinese), etc.\n"
            f"- 'nearby' → {radius_defaults.nearby}m\n"
            f"- 'walking distance' → {radius_defaults.walking}m\n"
            f"- No proximity signal → return null "
            f"(fallback to {radius_defaults.default}m)\n"
            "\n"
            "Extract search_location: Use your world knowledge to resolve named "
            "destinations to coordinates.\n"
            "- If query names a destination ('in Tokyo', 'in Sukhumvit', 'in Bali', "
            "'next to Asok BTS', 'near Shibuya') → return search_location as "
            "{\"lat\": <float>, \"lng\": <float>} for that destination.\n"
            "- If query implies current location ('nearby', 'near me', 'around here') "
            "or has no location signal → return search_location as null. "
            "The system will use the user's device GPS location as fallback.\n"
            "\n"
            "Extract discovery_filters as a dict for the Google Places Nearby Search API.\n"
            "This is the PRIMARY source of filters — it maps all cuisine and venue "
            "signals into Google Places API query parameters.\n"
            "\n"
            "Rules:\n"
            "- If query mentions a cuisine or venue type → set 'type' to the closest "
            "Google Places type:\n"
            "  ramen, sushi, pizza, burger, thai food, any cuisine → 'restaurant'\n"
            "  coffee, cafe, coffee shop → 'cafe'\n"
            "  bar, pub, beer → 'bar'\n"
            "  club, nightclub → 'night_club'\n"
            "  hotel, hostel, resort → 'lodging'\n"
            "  AND set 'keyword' to the specific cuisine or venue name from the query "
            "(e.g. 'ramen', 'coffee shop', 'rooftop bar')\n"
            "- If query signals 'open now' or 'currently open' → add 'opennow': true\n"
            "- Combine all relevant filters in discovery_filters dict. This is the "
            "only place cuisine/venue mappings should appear.\n"
            "\n"
            "Examples:\n"
            "- 'cheap ramen nearby' → discovery_filters: {'type': 'restaurant', 'keyword': 'ramen'}\n"
            "- 'coffee shop open now' → discovery_filters: {'type': 'cafe', 'keyword': 'coffee shop', 'opennow': true}\n"
            "- 'bar near Asok' → discovery_filters: {'type': 'bar'}\n"
            "- 'dinner nearby' → discovery_filters: {'type': 'restaurant', 'keyword': 'dinner'}\n"
            "\n"
            "Set validate_candidates to true if and only if discovery_filters contains "
            "'opennow': true.\n"
            "\n"
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

            # Set search_location: LLM-resolved destination takes precedence
            # Request location is fallback only (when LLM returns null)
            if result.search_location is None and location:
                result.search_location = location
            # If LLM resolved a destination, use it; if not and request location
            # is missing, ConsultService will handle graceful fallback with None

            if generation:
                generation.end(output=result.model_dump())

            return result
        except Exception:
            if generation:
                generation.end(error=str(Exception))
            raise
