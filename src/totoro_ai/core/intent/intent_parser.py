"""Intent extraction from natural language queries using Instructor.

`ParsedIntent` is the nested shape defined in ADR-056:

- `ParsedIntent.place` — field names mirror PlaceObject / PlaceAttributes
  exactly so construction of `RecallFilters` and consult filters is a
  straight assignment with no translation layer.
- `ParsedIntent.search` — search mechanics (radius, enriched_query,
  discovery_filters, search_location_name) consumed by ConsultService.
  `search_location` is excluded from the LLM schema via
  `Field(exclude=True)` and filled in by ConsultService after geocoding.
"""

from __future__ import annotations

import textwrap
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from totoro_ai.core.config import get_config
from totoro_ai.core.places.models import PlaceAttributes, PlaceType
from totoro_ai.providers import get_instructor_client, get_langfuse_client


class ParsedIntentPlace(BaseModel):
    """Place-side of a parsed intent — mirrors PlaceObject structure.

    Top-level fields (`place_type`, `subcategory`, `tags`) match `PlaceObject`
    Tier 1. `attributes` is a nested `PlaceAttributes`, the same type used by
    `PlaceObject.attributes`, so every `intent.place.attributes.*` path
    matches `place.attributes.*` 1:1
    (e.g. `intent.place.attributes.location_context.neighborhood`).

    `PlaceObject.source` is intentionally absent here: it is set by the
    save tool from the URL type, not inferred from a user query, so there
    is no intent-side equivalent for the LLM to populate.

    Fields the user did not express are left at their default (None / []).
    """

    place_type: PlaceType | None = None
    subcategory: str | None = None
    tags: list[str] = Field(default_factory=list)
    attributes: PlaceAttributes = Field(default_factory=PlaceAttributes)

    model_config = ConfigDict(extra="forbid")


class ParsedIntentSearch(BaseModel):
    """Search-side of a parsed intent — mechanics consumed by ConsultService.

    `search_location` is excluded from the LLM output schema so the model
    never tries to hallucinate coordinates; ConsultService fills it in
    after calling the geocoder with `search_location_name`.
    """

    radius_m: int | None = None
    enriched_query: str | None = None
    """Keyword-dense rewrite of the raw query OR `None` for meta-queries
    (browse/list/pull-my-saves). Consumers:
      - `RecallService`: `None` → filter-mode dispatch (WHERE clauses
         from `ParsedIntent.place` only, no vector/FTS).
      - `ConsultService`: falls back to the raw user message when `None`
         (consult always needs *some* text for discovery keyword)."""

    discovery_filters: dict[str, Any] = Field(default_factory=dict)
    """Google Places subtype hint ONLY. Keys: `type`, `opennow`. Nothing else."""

    search_location_name: str | None = None
    """Raw LLM capture of the location (e.g. "Sukhumvit", "Asok BTS")."""

    search_location: dict[str, float] | None = Field(default=None, exclude=True)
    """Resolved `{'lat': float, 'lng': float}`. Excluded from the LLM schema —
    ConsultService fills this after geocoding `search_location_name`."""

    model_config = ConfigDict(extra="forbid")


class ParsedIntent(BaseModel):
    """Nested intent shape (ADR-056).

    Two logical groups live side-by-side:
    * `place` mirrors PlaceObject / PlaceAttributes (flat, for straight
      RecallFilters construction).
    * `search` carries mechanics specific to the consult flow.
    """

    place: ParsedIntentPlace = Field(default_factory=ParsedIntentPlace)
    search: ParsedIntentSearch = Field(default_factory=ParsedIntentSearch)

    model_config = ConfigDict(extra="forbid")


class IntentParser:
    """Extract structured intent from natural language place recommendation queries."""

    def __init__(self) -> None:
        self._client = get_instructor_client("intent_parser")

    async def parse(
        self, query: str, user_memories: list[str] | None = None
    ) -> ParsedIntent:
        """Extract structured intent from a raw natural language query.

        `search.search_location` is always None here — ConsultService
        resolves coordinates from `search.search_location_name` after parsing.
        """
        lf = get_langfuse_client()

        config = get_config()
        nearby_radius_m = config.consult.nearby_radius_m
        walking_radius_m = config.consult.walking_radius_m

        system_prompt = textwrap.dedent(
            f"""\
            Extract structured intent from a place recommendation query. Return a
            JSON object with two nested groups — `place` and `search` — and
            nothing outside those two keys.

            `place` — fields that describe the place the user wants. The
            structure mirrors PlaceObject exactly:
            - place.place_type: one of "food_and_drink" | "things_to_do" |
              "shopping" | "services" | "accommodation" | null.
            - place.subcategory: must be one of the values below for the
              given place_type:
                food_and_drink: restaurant, cafe, bar, bakery, food_truck, brewery, dessert_shop
                things_to_do:   nature, cultural_site, museum, nightlife, experience, wellness, event_venue
                shopping:       market, boutique, mall, bookstore, specialty_store
                services:       coworking, laundry, pharmacy, atm, car_rental, barbershop
                accommodation:  hotel, hostel, rental, unique_stay
              Use null if the query does not clearly map to one of these values.
            - place.tags: list of free-form user-mentioned tags that do not
              fit a dedicated slot (e.g. ["rooftop", "view"]). Keep it short.
            - place.attributes.cuisine: "japanese" | "italian" | "thai" |
              "halal" | ... | null. Null for non-food queries.
            - place.attributes.price_hint: "cheap" | "moderate" | "expensive"
              | "luxury" | null. Canonical values — do NOT map from
              "low"/"mid"/"high".
                "cheap", "budget" → "cheap"
                "reasonable", "moderate" → "moderate"
                "nice", "upscale", "fancy" → "expensive"
                "luxury", "michelin", "splurge" → "luxury"
            - place.attributes.ambiance: single word ("cozy", "romantic",
              "lively", "quiet", "trendy", "casual"). Null if unspecified.
            - place.attributes.dietary: list of constraints ("vegetarian",
              "vegan", "halal", "kosher", "gluten-free"). Food-only.
            - place.attributes.good_for: list of use cases (["date-night"],
              ["solo"], ["groups"], ["families"], ["business"], ["late-night"]).
              Hyphenate multi-word.
            - place.attributes.location_context.neighborhood / .city /
              .country: the location names mentioned in the query
              ("Sukhumvit", "Tokyo", "Japan"). Null otherwise.

            `search` — mechanics the consult pipeline uses:
            - radius_m: integer metres or null. Proximity in any language:
                "nearby", "near me", "around here", "قريب", "附近" → {nearby_radius_m}
                "walking distance" → {walking_radius_m}
                no signal → null.
            - enriched_query: keyword-dense rewrite OR null. For a query
              that describes the kind of place the user wants, rewrite into
              a short keyword-dense phrase that folds in every signal above
              (cuisine, price, ambiance, dietary, good_for). Incorporate
              applicable user memories when supplied. Grammar does not
              matter — keyword density does.

              SET enriched_query TO null for META-QUERIES where the user is
              asking to browse, list, or retrieve their saved places
              without describing what they're looking for. These have no
              place-description content to enrich, and echoing the raw
              query into FTS produces a strict AND-match over filler
              words ("pull", "save", "show") that never appears in any
              document. For meta-queries, `place.place_type` /
              `place.subcategory` / `place.attributes.location_context`
              already carry all the structured signal the recall service
              needs; enriched_query must be null so the service can
              dispatch to filter-mode.

              Meta-query examples (enriched_query = null):
                "Can you pull all restaurants I saved?"          → null
                "Show me everything I saved in Bangkok"          → null
                "What have I saved from TikTok?"                 → null
                "Pull my saved places"                           → null
                "List all the cafes I bookmarked"                → null

              Place-description examples (enriched_query populated):
                "cozy ramen place near my office"
                  → "cozy ramen restaurant nearby"
                "somewhere quiet for a date tonight"
                  → "quiet romantic restaurant date night"
                "cheap pad thai in Sukhumvit"
                  → "cheap thai pad thai Sukhumvit"

              IMPORTANT — counter-examples. These CONTAIN "I saved" /
              "I bookmarked" / "from my saves" but are place-description
              queries, NOT meta-queries, because the user is describing a
              specific place they're trying to recall by attribute:
                "that pad thai place I saved"
                  → "pad thai restaurant"
                "the ramen spot I bookmarked"
                  → "ramen restaurant"
                "that cozy cafe I saved last week"
                  → "cozy cafe"
                "the Japanese place from my saves"
                  → "japanese restaurant"
                "the sushi place I saved in Tokyo"
                  → "sushi restaurant Tokyo"

              The decision rule: does the query describe a PLACE — cuisine
              (pad thai, ramen, sushi), venue type (cafe, bar, bookstore),
              vibe (cozy, quiet, upscale), or name fragment? If yes, it's
              a place-description query — populate enriched_query. If the
              user is only asking to see a list with no describing
              attributes ("pull my saves", "show me everything"), it's a
              meta-query — enriched_query = null.
            - discovery_filters: dict for Google Places Nearby Search. Keep
              ONLY `"type"` (restaurant | cafe | bar | night_club | lodging)
              and `"opennow": true` (only when the query explicitly says so).
              Do NOT duplicate cuisine / price / keyword here — those have
              dedicated slots above. Empty `{{}}` if neither key applies.
            - search_location_name: the location name as mentioned. Do not
              resolve to coordinates. Null if the query implies current
              location or names no place.

            Return null / [] / {{}} for anything the query does not address.
            Do not invent values.

            Examples:

            Query: "cheap ramen nearby"
            Output: {{
              "place": {{
                "place_type": "food_and_drink",
                "subcategory": "restaurant",
                "attributes": {{
                  "cuisine": "japanese",
                  "price_hint": "cheap"
                }}
              }},
              "search": {{
                "radius_m": {nearby_radius_m},
                "enriched_query": "cheap japanese ramen nearby",
                "discovery_filters": {{"type": "restaurant"}}
              }}
            }}

            Query: "nice dinner in Sukhumvit for a date"
            Output: {{
              "place": {{
                "place_type": "food_and_drink",
                "attributes": {{
                  "price_hint": "expensive",
                  "good_for": ["date-night"],
                  "location_context": {{"neighborhood": "Sukhumvit"}}
                }}
              }},
              "search": {{
                "search_location_name": "Sukhumvit",
                "enriched_query": "upscale romantic dinner Sukhumvit date",
                "discovery_filters": {{"type": "restaurant"}}
              }}
            }}

            Query: "quiet museum in Tokyo for a rainy afternoon"
            Output: {{
              "place": {{
                "place_type": "things_to_do",
                "subcategory": "museum",
                "attributes": {{
                  "ambiance": "quiet",
                  "location_context": {{"city": "Tokyo"}}
                }}
              }},
              "search": {{
                "search_location_name": "Tokyo",
                "enriched_query": "quiet museum Tokyo indoors rainy afternoon",
                "discovery_filters": {{"type": "museum"}}
              }}
            }}

            Query: "boutique hotel near the beach for a honeymoon"
            Output: {{
              "place": {{
                "place_type": "accommodation",
                "subcategory": "hotel",
                "tags": ["boutique", "beach"],
                "attributes": {{
                  "ambiance": "romantic",
                  "good_for": ["honeymoon"]
                }}
              }},
              "search": {{
                "enriched_query": "boutique romantic beach hotel honeymoon",
                "discovery_filters": {{"type": "lodging"}}
              }}
            }}

            Query: "cute bookstore in Shibuya"
            Output: {{
              "place": {{
                "place_type": "shopping",
                "subcategory": "bookstore",
                "attributes": {{
                  "ambiance": "cozy",
                  "location_context": {{"neighborhood": "Shibuya"}}
                }}
              }},
              "search": {{
                "search_location_name": "Shibuya",
                "enriched_query": "cute cozy bookstore Shibuya",
                "discovery_filters": {{"type": "book_store"}}
              }}
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

            # ADR-057 follow-up: `enriched_query` is legitimately `None`
            # for meta-queries (pull/list/show my saves). Collapse empty
            # strings to None so downstream `None`-checks are sufficient.
            if result.search.enriched_query == "":
                result.search.enriched_query = None

            if generation:
                generation.end(output=result.model_dump())

            return result
        except Exception as exc:
            if generation:
                generation.end(error=str(exc))
            raise


__all__ = ["IntentParser", "ParsedIntent", "ParsedIntentPlace", "ParsedIntentSearch"]
