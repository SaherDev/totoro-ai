"""
Tag-based PlaceQuery patterns for places_v2.

Tags carry type, value, and source.  Querying uses values only (AND semantics).
Every example below maps a human intent to a PlaceQuery the system can execute.

Tag types in use:
  "cuisine"     — Thai, Japanese, Italian, Korean, Mexican, …
  "dietary"     — vegan, vegetarian, halal, vegetarian_options
  "price"       — $  $$  $$$  $$$$
  "feature"     — outdoor_seating, live_music, dog_friendly, family_friendly,
                  group_friendly, sports_viewing, kids_menu
  "service"     — dine_in, takeout, delivery, reservable, serves_beer,
                  serves_wine, serves_cocktails, serves_breakfast,
                  serves_brunch, serves_lunch, serves_dinner
  "atmosphere"  — cozy, romantic, trendy, lively, quiet  (LLM-sourced)
"""

from __future__ import annotations

from totoro_ai.core.places_v2.models import (
    LocationContext,
    PlaceCategory,
    PlaceQuery,
)

# ---------------------------------------------------------------------------
# 1. Cuisine
# ---------------------------------------------------------------------------

find_thai = PlaceQuery(
    tags=["Thai"],
)

find_japanese = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["Japanese"],
)

find_ramen = PlaceQuery(
    # "ramen" is a cuisine tag produced by _GOOGLE_TYPE_TO_CUISINE
    tags=["Japanese"],
    # narrow further with a text search in the caller if needed
)

# ---------------------------------------------------------------------------
# 2. Dietary restrictions
# ---------------------------------------------------------------------------

find_vegan = PlaceQuery(
    tags=["vegan"],
)

find_vegetarian = PlaceQuery(
    tags=["vegetarian"],
)

find_halal = PlaceQuery(
    tags=["halal"],
)

# Strict vegan Thai — both tags must be present (AND)
find_vegan_thai = PlaceQuery(
    tags=["vegan", "Thai"],
)

find_halal_korean = PlaceQuery(
    tags=["halal", "Korean"],
)

# ---------------------------------------------------------------------------
# 3. Price
# ---------------------------------------------------------------------------

find_cheap_eats = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["$"],
)

find_mid_range = PlaceQuery(
    tags=["$$"],
)

find_splurge = PlaceQuery(
    tags=["$$$"],
)

# Budget sushi
find_cheap_japanese = PlaceQuery(
    tags=["Japanese", "$"],
)

# ---------------------------------------------------------------------------
# 4. Features / vibes
# ---------------------------------------------------------------------------

find_outdoor_seating = PlaceQuery(
    tags=["outdoor_seating"],
)

find_dog_friendly = PlaceQuery(
    tags=["dog_friendly"],
)

find_live_music = PlaceQuery(
    tags=["live_music"],
)

find_sports_bar = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["sports_viewing"],
)

find_family_friendly = PlaceQuery(
    tags=["family_friendly", "kids_menu"],
)

# Cozy atmosphere (LLM-tagged places; only present once LLM enrichment runs)
find_cozy = PlaceQuery(
    tags=["cozy"],
)

find_romantic = PlaceQuery(
    tags=["romantic"],
)

find_trendy = PlaceQuery(
    tags=["trendy"],
)

# ---------------------------------------------------------------------------
# 5. Service capabilities
# ---------------------------------------------------------------------------

find_delivery = PlaceQuery(
    tags=["delivery"],
)

find_takeout = PlaceQuery(
    tags=["takeout"],
)

find_reservable = PlaceQuery(
    tags=["reservable"],
)

find_breakfast_spots = PlaceQuery(
    tags=["serves_breakfast"],
)

find_cocktail_bars = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["serves_cocktails"],
)

# ---------------------------------------------------------------------------
# 6. Combined intents — real user scenarios
# ---------------------------------------------------------------------------

# "I want cheap outdoor Thai food"
cheap_outdoor_thai = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["Thai", "outdoor_seating", "$"],
)

# "Find me a romantic dinner spot, not too expensive"
romantic_dinner = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["romantic", "$$"],
)

# "Somewhere I can take my dog for brunch"
dog_brunch = PlaceQuery(
    tags=["dog_friendly", "serves_brunch"],
)

# "Vegan-friendly group dinner"
vegan_group = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["vegan", "group_friendly"],
)

# "Cozy café for solo work, not a chain"
solo_work_cafe = PlaceQuery(
    category=PlaceCategory.cafe,
    tags=["cozy"],
)

# "Pre-game drinks with outdoor seating"
outdoor_drinks = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["outdoor_seating", "serves_beer"],
)

# "Halal Korean BBQ"
halal_korean_bbq = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["Korean", "halal"],
)

# "Trendy rooftop cocktail bar"
trendy_cocktails = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["trendy", "serves_cocktails", "outdoor_seating"],
)

# "Family lunch on a budget"
family_budget_lunch = PlaceQuery(
    tags=["family_friendly", "serves_lunch", "$"],
)

# "Late-night delivery, something spicy"
# Note: "spicy" is an atmosphere/feature tag added by LLM enrichment
late_night_delivery = PlaceQuery(
    tags=["delivery"],
    # add tags=["spicy"] once LLM enrichment is wired
)

# ---------------------------------------------------------------------------
# 7. Location-scoped queries
# ---------------------------------------------------------------------------

# Same patterns above, but scoped to a geo radius
nearby_vegan = PlaceQuery(
    tags=["vegan"],
    location=LocationContext(
        lat=13.7563,
        lng=100.5018,
        radius_m=1000,
    ),
)

nearby_cheap_thai = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["Thai", "$"],
    location=LocationContext(
        lat=13.7563,
        lng=100.5018,
        radius_m=500,
    ),
)

# Neighbourhood scoping (no radius, string match on location.neighborhood)
sukhumvit_japanese = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["Japanese"],
    location=LocationContext(neighborhood="Sukhumvit"),
)

bangkok_outdoor_cafes = PlaceQuery(
    category=PlaceCategory.cafe,
    tags=["outdoor_seating"],
    location=LocationContext(city="Bangkok"),
)

# ---------------------------------------------------------------------------
# 8. Category-only (no tags needed)
# ---------------------------------------------------------------------------

# Sometimes category alone is the right filter
all_museums = PlaceQuery(category=PlaceCategory.museum)
all_night_markets = PlaceQuery(category=PlaceCategory.night_market)
nearby_parks = PlaceQuery(
    category=PlaceCategory.park,
    location=LocationContext(lat=13.7563, lng=100.5018, radius_m=2000),
)
