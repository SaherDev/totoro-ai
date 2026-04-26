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

all_museums = PlaceQuery(category=PlaceCategory.museum)
all_night_markets = PlaceQuery(category=PlaceCategory.night_market)
nearby_parks = PlaceQuery(
    category=PlaceCategory.park,
    location=LocationContext(lat=13.7563, lng=100.5018, radius_m=2000),
)

# ---------------------------------------------------------------------------
# 9. Time of day
# ---------------------------------------------------------------------------

# Morning (6am–11am) — breakfast, coffee, early work
morning_coffee = PlaceQuery(
    category=PlaceCategory.cafe,
    tags=["serves_breakfast"],
)

morning_breakfast = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["serves_breakfast"],
)

early_work_session = PlaceQuery(
    category=PlaceCategory.cafe,
    tags=["serves_breakfast", "cozy"],
)

# Late morning (10am–1pm) — brunch
brunch_outdoor = PlaceQuery(
    tags=["serves_brunch", "outdoor_seating"],
)

brunch_with_drinks = PlaceQuery(
    tags=["serves_brunch", "serves_cocktails"],
)

dog_friendly_brunch = PlaceQuery(
    tags=["serves_brunch", "dog_friendly"],
)

# Midday (12pm–3pm) — lunch, quick eats
lunch_quick = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["serves_lunch", "takeout"],
)

lunch_outdoor = PlaceQuery(
    tags=["serves_lunch", "outdoor_seating"],
)

lunch_budget = PlaceQuery(
    tags=["serves_lunch", "$"],
)

# Afternoon (2pm–6pm) — coffee, study, snacks
afternoon_study = PlaceQuery(
    category=PlaceCategory.cafe,
    tags=["cozy"],
)

afternoon_dessert = PlaceQuery(
    category=PlaceCategory.dessert_shop,
)

afternoon_tea = PlaceQuery(
    category=PlaceCategory.tea_house,
)

study_cafe_afternoon = PlaceQuery(
    category=PlaceCategory.study_cafe,
    tags=["quiet"],  # LLM-tagged
)

# Evening (6pm–10pm) — dinner, pre-drinks
dinner_date = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["serves_dinner", "romantic", "$$"],
)

dinner_group = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["serves_dinner", "group_friendly"],
)

pre_dinner_cocktails = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["serves_cocktails", "reservable"],
)

family_dinner = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["serves_dinner", "family_friendly"],
)

# Night (9pm–late) — bars, clubs, night food
night_cocktail_bar = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["serves_cocktails", "trendy"],
)

night_market_food = PlaceQuery(
    category=PlaceCategory.night_market,
)

night_live_music = PlaceQuery(
    category=PlaceCategory.live_music_venue,
    tags=["live_music"],
)

night_karaoke = PlaceQuery(
    category=PlaceCategory.karaoke,
)

late_night_delivery = PlaceQuery(
    tags=["delivery"],
)

after_midnight_eats = PlaceQuery(
    category=PlaceCategory.street_food,
)

# ---------------------------------------------------------------------------
# 10. Season / weather
# ---------------------------------------------------------------------------

# Hot / summer — outdoor, cold drinks, water, shade
summer_outdoor_dining = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["outdoor_seating", "$$"],
)

summer_beach_eats = PlaceQuery(
    category=PlaceCategory.restaurant,
    location=LocationContext(city="Phuket"),
    tags=["outdoor_seating"],
)

summer_rooftop_drinks = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["outdoor_seating", "serves_cocktails"],
)

hot_day_dessert = PlaceQuery(
    category=PlaceCategory.ice_cream_shop,
)

summer_juice_bar = PlaceQuery(
    category=PlaceCategory.juice_bar,
)

# Rainy / indoor — cozy, delivery, covered spots
rainy_day_cafe = PlaceQuery(
    category=PlaceCategory.cafe,
    tags=["cozy"],
)

rainy_day_delivery = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["delivery"],
)

rainy_indoor_activity = PlaceQuery(
    category=PlaceCategory.museum,
)

rainy_shopping = PlaceQuery(
    category=PlaceCategory.shopping_mall,
)

rainy_bowling = PlaceQuery(
    category=PlaceCategory.bowling_alley,
)

# Cool / winter — warmth, hot drinks, hot food
cool_weather_hotpot = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["$$"],
    # "hotpot" would come from LLM cuisine tagging
)

cool_weather_ramen = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["Japanese"],
)

warm_coffee_cozy = PlaceQuery(
    category=PlaceCategory.cafe,
    tags=["cozy"],
)

hot_spring_visit = PlaceQuery(
    category=PlaceCategory.hot_spring,
)

cool_spa_day = PlaceQuery(
    category=PlaceCategory.spa,
)

# ---------------------------------------------------------------------------
# 11. Social occasion
# ---------------------------------------------------------------------------

# Solo
solo_work_anywhere = PlaceQuery(
    category=PlaceCategory.cafe,
    tags=["quiet", "cozy"],
)

solo_ramen_quick = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["Japanese", "takeout"],
)

solo_museum_afternoon = PlaceQuery(
    category=PlaceCategory.museum,
)

# Date night
date_night_italian = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["Italian", "romantic", "$$$"],
)

date_night_cocktails = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["romantic", "serves_cocktails"],
)

date_night_experience = PlaceQuery(
    category=PlaceCategory.live_music_venue,
    tags=["live_music", "romantic"],
)

# Group / friends
group_korean_bbq = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["Korean", "group_friendly"],
)

group_karaoke_drinks = PlaceQuery(
    category=PlaceCategory.karaoke,
)

group_sports_bar = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["sports_viewing", "serves_beer"],
)

friends_brunch = PlaceQuery(
    tags=["serves_brunch", "group_friendly", "$$"],
)

# Family
family_lunch_kids = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["family_friendly", "kids_menu", "serves_lunch"],
)

family_park_picnic = PlaceQuery(
    category=PlaceCategory.park,
)

family_aquarium = PlaceQuery(
    category=PlaceCategory.aquarium,
)

# Work meeting / client
client_lunch = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["serves_lunch", "reservable", "$$"],
)

casual_work_coffee = PlaceQuery(
    category=PlaceCategory.cafe,
    tags=["quiet"],
)

team_dinner = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["group_friendly", "serves_dinner", "$$$"],
)

# ---------------------------------------------------------------------------
# 12. Special occasion
# ---------------------------------------------------------------------------

anniversary_dinner = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["romantic", "$$$", "reservable"],
)

birthday_group = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["group_friendly", "serves_cocktails", "$$$"],
)

celebration_rooftop = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["outdoor_seating", "serves_cocktails", "trendy"],
)

farewell_drinks = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["group_friendly", "serves_beer"],
)

# ---------------------------------------------------------------------------
# 13. Health / fitness context
# ---------------------------------------------------------------------------

pre_workout_coffee = PlaceQuery(
    category=PlaceCategory.cafe,
    tags=["serves_breakfast"],
)

post_workout_smoothie = PlaceQuery(
    category=PlaceCategory.juice_bar,
)

post_workout_protein = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["serves_lunch"],
    # "high-protein" would be an LLM atmosphere tag
)

healthy_vegan_lunch = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["vegan", "serves_lunch"],
)

spa_recovery = PlaceQuery(
    category=PlaceCategory.spa,
)

yoga_studio_nearby = PlaceQuery(
    category=PlaceCategory.yoga_studio,
    location=LocationContext(lat=13.7563, lng=100.5018, radius_m=1000),
)

# ---------------------------------------------------------------------------
# 14. Budget-conscious
# ---------------------------------------------------------------------------

cheapest_meal = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["$"],
)

street_food_crawl = PlaceQuery(
    category=PlaceCategory.street_food,
)

budget_vegan = PlaceQuery(
    tags=["vegan", "$"],
)

cheap_delivery_tonight = PlaceQuery(
    tags=["delivery", "$"],
)

free_afternoon = PlaceQuery(
    category=PlaceCategory.park,
    # parks are free; combine with neighbourhood for nearby options
    location=LocationContext(lat=13.7563, lng=100.5018, radius_m=2000),
)

# ---------------------------------------------------------------------------
# 15. Treat yourself / splurge
# ---------------------------------------------------------------------------

splurge_omakase = PlaceQuery(
    category=PlaceCategory.restaurant,
    tags=["Japanese", "$$$$", "reservable"],
)

splurge_cocktail_bar = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["$$$$", "serves_cocktails", "trendy"],
)

splurge_spa = PlaceQuery(
    category=PlaceCategory.spa,
    tags=["$$$"],
)

luxury_hotel_bar = PlaceQuery(
    category=PlaceCategory.bar,
    tags=["romantic", "$$$"],
)
