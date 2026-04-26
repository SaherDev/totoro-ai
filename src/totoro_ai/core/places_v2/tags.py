"""Known tag vocabulary for places_v2.

All enums are str-based so their values drop directly into PlaceQuery.tags
without conversion.  PlaceTag.type and PlaceTag.value remain plain str to
allow LLM-generated tags that extend beyond these known values.

Usage:
    PlaceQuery(tags=[CuisineTag.thai, FeatureTag.outdoor_seating])
    PlaceTag(type=TagType.cuisine, value=CuisineTag.thai, source="google")
"""

from __future__ import annotations

from enum import Enum


class TagType(str, Enum):
    """Controlled set of tag type identifiers."""

    cuisine = "cuisine"
    dietary = "dietary"
    feature = "feature"       # observable physical/structural attributes
    atmosphere = "atmosphere"  # vibe/mood — LLM-sourced
    service = "service"        # operational capabilities
    price = "price"


# ---------------------------------------------------------------------------
# Cuisine
# ---------------------------------------------------------------------------

class CuisineTag(str, Enum):
    thai = "Thai"
    japanese = "Japanese"
    korean = "Korean"
    chinese = "Chinese"
    italian = "Italian"
    french = "French"
    mexican = "Mexican"
    indian = "Indian"
    vietnamese = "Vietnamese"
    mediterranean = "Mediterranean"
    american = "American"
    greek = "Greek"
    spanish = "Spanish"
    turkish = "Turkish"
    indonesian = "Indonesian"
    middle_eastern = "Middle Eastern"
    brazilian = "Brazilian"
    seafood = "Seafood"
    steakhouse = "Steakhouse"


# ---------------------------------------------------------------------------
# Dietary
# ---------------------------------------------------------------------------

class DietaryTag(str, Enum):
    vegan = "vegan"
    vegetarian = "vegetarian"
    halal = "halal"
    vegetarian_options = "vegetarian_options"  # not fully vegan/veg menu


# ---------------------------------------------------------------------------
# Feature — observable, often Google-sourced
# ---------------------------------------------------------------------------

class FeatureTag(str, Enum):
    outdoor_seating = "outdoor_seating"
    live_music = "live_music"
    dog_friendly = "dog_friendly"
    family_friendly = "family_friendly"
    group_friendly = "group_friendly"
    sports_viewing = "sports_viewing"
    kids_menu = "kids_menu"
    rooftop = "rooftop"          # LLM-tagged (no Google boolean)
    waterfront = "waterfront"    # LLM-tagged
    private_room = "private_room"  # LLM-tagged
    garden = "garden"            # LLM-tagged
    fireplace = "fireplace"      # LLM-tagged


# ---------------------------------------------------------------------------
# Atmosphere — vibe/mood, LLM-sourced
# ---------------------------------------------------------------------------

class AtmosphereTag(str, Enum):
    cozy = "cozy"
    romantic = "romantic"
    trendy = "trendy"
    quiet = "quiet"
    lively = "lively"
    intimate = "intimate"
    spacious = "spacious"
    vibrant = "vibrant"
    laid_back = "laid_back"
    luxurious = "luxurious"
    casual = "casual"
    upscale = "upscale"
    hidden_gem = "hidden_gem"
    instagram_worthy = "instagram_worthy"
    vintage = "vintage"
    industrial = "industrial"
    minimalist = "minimalist"
    bohemian = "bohemian"
    traditional = "traditional"
    modern = "modern"


# ---------------------------------------------------------------------------
# Service — operational capabilities, Google-sourced
# ---------------------------------------------------------------------------

class ServiceTag(str, Enum):
    dine_in = "dine_in"
    takeout = "takeout"
    delivery = "delivery"
    reservable = "reservable"
    serves_breakfast = "serves_breakfast"
    serves_brunch = "serves_brunch"
    serves_lunch = "serves_lunch"
    serves_dinner = "serves_dinner"
    serves_beer = "serves_beer"
    serves_wine = "serves_wine"
    serves_cocktails = "serves_cocktails"


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------

class PriceTag(str, Enum):
    free = "free"
    budget = "$"
    moderate = "$$"
    expensive = "$$$"
    very_expensive = "$$$$"
