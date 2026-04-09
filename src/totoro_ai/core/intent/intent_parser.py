"""Intent extraction from natural language queries using Instructor."""

import textwrap
from typing import Any, cast

from pydantic import BaseModel

from totoro_ai.providers import get_instructor_client, get_langfuse_client


class _IntentLLMOutput(BaseModel):
    """Schema for LLM extraction only. Not used outside this module."""

    occasion: str | None = None
    price_range: str | None = None
    radius: int | None = None
    discovery_filters: dict[str, Any] = {}
    search_location_name: str | None = None


class ParsedIntent(BaseModel):
    """Structured representation of user intent extracted from a query."""

    occasion: str | None = None
    """Context/occasion (e.g., 'date night', 'quick lunch'), or None if not specified.
    """

    price_range: str | None = None
    """Price range preference ('low', 'mid', 'high'), or None if not specified."""

    radius: int | None = None
    """Preferred search radius in meters. LLM returns null when no radius signal
    detected; falls back to config default."""

    discovery_filters: dict[str, Any] = {}
    """Filters to pass to PlacesClient.discover() (e.g., opennow, type, keyword)."""

    search_location_name: str | None = None
    """Raw location name extracted by LLM (e.g., 'Sukhumvit', 'Asok BTS').
    Preserved for observability; coordinates live in search_location."""

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
        self, query: str, user_memories: list[str] | None = None
    ) -> ParsedIntent:
        """Extract structured intent from a raw natural language query.

        Uses GPT-4o-mini via Instructor for reliable structured extraction.
        search_location is always None here — ConsultService resolves coordinates
        from search_location_name after parsing.

        Args:
            query: Raw natural language query from user
            user_memories: Optional list of user's personal facts (ADR-010)

        Returns:
            ParsedIntent with extracted fields; search_location always None

        Raises:
            ValidationError: If LLM response fails Pydantic validation
                (FastAPI returns 422 to caller)
        """
        lf = get_langfuse_client()

        from totoro_ai.core.config import get_config

        config = get_config()
        radius_defaults = config.consult.radius_defaults

        system_prompt = textwrap.dedent(f"""\
            Extract structured intent from a place recommendation query. Return a JSON object with these fields:

            - occasion: string or null. Why the user wants this place (e.g. "date night", "work lunch", "solo breakfast").
            - price_range: "low" | "mid" | "high" | null. Map signals like "cheap", "budget" → "low". "nice", "upscale", "fancy" → "high". "moderate", "not too expensive" → "mid".
            - radius: integer (metres) or null. Infer from proximity language in any language:
              - "nearby", "near me", "around here", "قريب", "附近" → {radius_defaults.nearby}
              - "walking distance" → {radius_defaults.walking}
              - No proximity signal → null (system applies {radius_defaults.default} as fallback)
            - search_location_name: string or null. Extract the location name exactly as mentioned in the query ("Tokyo", "Sukhumvit", "Asok BTS", "Shibuya"). Do not resolve to coordinates. If the query implies current location or names no place → null.
            - discovery_filters: dict for Google Places Nearby Search API. This is the primary filter source. Build it from these rules:
              - Set "type" to the closest Google Places type:
                Any cuisine or food mention → "restaurant"
                Coffee, cafe → "cafe"
                Bar, pub, beer → "bar"
                Club, nightclub → "night_club"
                Hotel, hostel, resort → "lodging"
              - Set "keyword" to the specific term from the query (e.g. "ramen", "rooftop bar", "coffee shop"). Omit "keyword" if the query has no specific term beyond the type.
              - Add "opennow": true only if the query explicitly asks for currently open places.
              - If the query has no venue or cuisine signal → empty dict {{}}.

            Return null for any field the query does not address. Do not invent values.

            Examples:
            Query: "cheap ramen nearby"
            Output: {{"occasion": null, "price_range": "low", "radius": {radius_defaults.nearby}, "search_location_name": null, "discovery_filters": {{"type": "restaurant", "keyword": "ramen"}}}}

            Query: "nice dinner in Sukhumvit for a date"
            Output: {{"occasion": "date night", "price_range": "high", "radius": null, "search_location_name": "Sukhumvit", "discovery_filters": {{"type": "restaurant", "keyword": "dinner"}}}}

            Query: "coffee shop open now"
            Output: {{"occasion": null, "price_range": null, "radius": null, "search_location_name": null, "discovery_filters": {{"type": "cafe", "keyword": "coffee shop", "opennow": true}}}}

            Query: "bar near Asok"
            Output: {{"occasion": null, "price_range": null, "radius": null, "search_location_name": "Asok", "discovery_filters": {{"type": "bar"}}}}

            Query: "somewhere to eat"
            Output: {{"occasion": null, "price_range": null, "radius": null, "search_location_name": null, "discovery_filters": {{"type": "restaurant"}}}}""")

        # Inject user memories as context (ADR-010, ADR-044: XML-wrapped for safety)
        if user_memories:
            memories_xml = "\n".join(f"    <memory>{mem}</memory>" for mem in user_memories)
            system_prompt += f"""\n
<user_context>
<memories>
{memories_xml}
</memories>
</user_context>

Consider these user facts when interpreting the query. Use them to enhance intent parsing (e.g., if the user is vegetarian, infer dietary preferences from their query). Never contradict or reference the facts directly in the output — only use them to improve interpretation.
"""

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
            llm_output = cast(
                _IntentLLMOutput,
                await self._client.extract(
                    _IntentLLMOutput,
                    messages=messages,
                ),
            )

            result = ParsedIntent(
                occasion=llm_output.occasion,
                price_range=llm_output.price_range,
                radius=llm_output.radius,
                discovery_filters=llm_output.discovery_filters,
                search_location_name=llm_output.search_location_name,
            )

            if generation:
                generation.end(output=result.model_dump())

            return result
        except Exception:
            if generation:
                generation.end(error=str(Exception))
            raise
