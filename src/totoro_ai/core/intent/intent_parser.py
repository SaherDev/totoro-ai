"""Intent extraction from natural language queries using Instructor.

`ParsedIntent` is deliberately minimal: it carries only the fields that drive
actual dispatch decisions (place_type, radius, location, discovery filters)
plus `enriched_query`, which is the single text handle for vector search and
Google Places keyword lookup. Cuisine, price, ambiance, dietary, and other
attribute signals live *inside* `enriched_query` as plain text — the embedder
and the Places keyword handle them semantically, so there is no structured
duplicate on ParsedIntent.
"""

from __future__ import annotations

import textwrap
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from totoro_ai.core.places.models import PlaceType
from totoro_ai.providers import get_instructor_client, get_langfuse_client


class ParsedIntent(BaseModel):
    """Structured intent — the minimum set of fields that drive dispatch.

    Everything here either routes the pipeline (place_type, discovery_filters),
    constrains the search geometry (radius_m, search_location*), or feeds a
    text-matching stage (enriched_query). No structured attribute fields —
    cuisine / price / ambiance / dietary / good_for all travel inside
    `enriched_query` and the embedder handles them semantically.
    """

    place_type: PlaceType | None = None

    radius_m: int | None = None

    search_location_name: str | None = None
    """Raw LLM capture of the location (e.g. "Sukhumvit", "Asok BTS"). Not resolved."""

    search_location: dict[str, float] | None = None
    """Resolved {'lat': float, 'lng': float}. Filled by ConsultService after geocoding."""

    enriched_query: str = ""
    """Always present, non-empty. Feeds both the recall vector search and Google
    Places discovery `keyword` parameter. Cuisine, price, ambiance, dietary, and
    other attribute signals are folded into this string — the embedder and the
    Places keyword handle them semantically."""

    discovery_filters: dict[str, Any] = Field(default_factory=dict)
    """Google Places subtype hint ONLY. Keys: `type`, `opennow`. Nothing else."""

    model_config = ConfigDict(extra="forbid")


class IntentParser:
    """Extract structured intent from natural language place recommendation queries."""

    def __init__(self) -> None:
        self._client = get_instructor_client("intent_parser")

    async def parse(
        self, query: str, user_memories: list[str] | None = None
    ) -> ParsedIntent:
        """Extract structured intent from a raw natural language query.

        `search_location` is always None here — ConsultService resolves
        coordinates from `search_location_name` after parsing.
        """
        lf = get_langfuse_client()

        from totoro_ai.core.config import get_config

        config = get_config()
        nearby_radius_m = config.consult.nearby_radius_m
        walking_radius_m = config.consult.walking_radius_m

        system_prompt = textwrap.dedent(
            f"""\
            Extract structured intent from a place recommendation query. Return
            ONLY these fields — nothing else:

            - place_type: one of "food_and_drink" | "things_to_do" | "shopping" |
              "services" | "accommodation" | null. Any food/drink mention →
              "food_and_drink". Museum/park/attraction → "things_to_do". Shop/
              store/mall → "shopping". Hotel/hostel/resort → "accommodation".

            - radius_m: integer metres or null. Proximity in any language:
                "nearby", "near me", "around here", "قريب", "附近" → {nearby_radius_m}
                "walking distance" → {walking_radius_m}
                no signal → null (service falls back to a default).

            - search_location_name: the location name exactly as mentioned
              ("Tokyo", "Sukhumvit", "Asok BTS"). Do not resolve to coordinates.
              Null if the query implies current location or names no place.

            - enriched_query: ALWAYS non-empty. Rewrite the raw query into a
              short, keyword-dense phrase that folds in every signal the user
              gave: cuisine, price, ambiance, dietary, occasion, and anything
              else. This string feeds both the recall vector search and Google
              Places discovery — keyword density matters more than grammar. If
              user preferences are supplied, incorporate any that apply.
              Examples:
                raw "cheap ramen nearby" → "cheap japanese ramen nearby"
                raw "nice dinner in Sukhumvit for a date" → "upscale romantic dinner Sukhumvit"
                raw "somewhere relaxing for a solo coffee" → "cozy quiet cafe solo"
                raw "late night drinks" → "late night bar drinks"
                raw "halal food nearby" → "halal restaurant nearby"
                raw "dinner nearby" + memory "I'm vegetarian" → "vegetarian dinner nearby"
                If no signal to add, return the raw query verbatim.

            - discovery_filters: dict for the Google Places Nearby Search API.
              Keep ONLY these keys:
                "type": "restaurant" | "cafe" | "bar" | "night_club" | "lodging"
                  (include only when the query clearly targets one).
                "opennow": true (ONLY if the query explicitly asks for "open now").
              Do NOT include cuisine, price, keyword, or anything else. If
              neither key applies, return {{}}.

            Do NOT return cuisine, subcategory, price_hint, ambiance, dietary,
            good_for, tags, neighborhood, city, country, source, or any other
            attribute field. Fold those into `enriched_query` as text.

            Examples:

            Query: "cheap ramen nearby"
            Output: {{
              "place_type": "food_and_drink",
              "radius_m": {nearby_radius_m},
              "enriched_query": "cheap japanese ramen nearby",
              "discovery_filters": {{"type": "restaurant"}}
            }}

            Query: "nice dinner in Sukhumvit for a date"
            Output: {{
              "place_type": "food_and_drink",
              "search_location_name": "Sukhumvit",
              "enriched_query": "upscale romantic dinner Sukhumvit date",
              "discovery_filters": {{"type": "restaurant"}}
            }}

            Query: "somewhere relaxing for a solo coffee"
            Output: {{
              "place_type": "food_and_drink",
              "enriched_query": "cozy quiet cafe solo coffee",
              "discovery_filters": {{"type": "cafe"}}
            }}

            Query: "late night drinks"
            Output: {{
              "place_type": "food_and_drink",
              "enriched_query": "late night bar drinks",
              "discovery_filters": {{"type": "bar"}}
            }}

            Query: "halal food nearby"
            Output: {{
              "place_type": "food_and_drink",
              "radius_m": {nearby_radius_m},
              "enriched_query": "halal restaurant nearby",
              "discovery_filters": {{"type": "restaurant"}}
            }}
            """
        )

        if user_memories:
            memories_text = ", ".join(f'"{m}"' for m in user_memories)
            user_content = f"User preferences: [{memories_text}]\n\nQuery: {query}"
        else:
            user_content = query

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        generation = None
        if lf:
            generation = lf.generation(
                name="intent_parsing",
                input={"system": system_prompt, "user": query},
            )

        try:
            result = cast(
                ParsedIntent,
                await self._client.extract(
                    ParsedIntent,
                    messages=messages,
                ),
            )
            if not result.enriched_query:
                result.enriched_query = query
            result.search_location = None

            if generation:
                generation.end(output=result.model_dump())

            return result
        except Exception as exc:
            if generation:
                generation.end(error=str(exc))
            raise


__all__ = ["IntentParser", "ParsedIntent"]
