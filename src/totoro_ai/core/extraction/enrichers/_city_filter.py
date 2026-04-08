"""Shared city sanitisation used by emoji_regex and llm_ner enrichers."""

import difflib

# Words that are never valid city names — content tags, topic labels, venue/mall
# names, and hashtag-derived tokens that slip through after # stripping.
CITY_BLOCKLIST: frozenset[str] = frozenset(
    {
        "mall",
        "paragon",
        "shoppingmall",
        "siamparagon",
        "centralworld",
        "emquartier",
        "emsphere",
        "iconsiam",
        "majorcineplaex",
        "terminalmedical",
        "food",
        "travel",
        "vlog",
        "fyp",
        "foryou",
        "thailand",
        "tiktok",
        "foodie",
        "bangkokfood",
        "bangkokeats",
        "bangkokfoodie",
        "bangkokrestaurant",
        "thaifood",
        "streetfood",
        "thonglor",
        "ploenchit",
        "asok",
        "nana",
        "chinatown",
    }
)

# Canonical city names used for fuzzy correction and the single-word allowlist.
# Keys are lowercase for matching; values are the correctly-cased display name.
_KNOWN_CITIES: dict[str, str] = {
    "bangkok": "Bangkok",
    "london": "London",
    "tokyo": "Tokyo",
    "paris": "Paris",
    "singapore": "Singapore",
    "kuala lumpur": "Kuala Lumpur",
    "seoul": "Seoul",
    "jakarta": "Jakarta",
    "new york": "New York",
    "los angeles": "Los Angeles",
    "sydney": "Sydney",
    "melbourne": "Melbourne",
}


def sanitize_city(city: str | None) -> str | None:
    """Return None if city is a hashtag token or a known non-city label.

    For single-word lowercase values (likely hashtag-derived), fuzzy-matches
    against known real city names before rejecting — corrects typos like
    "bangok" → "Bangkok" instead of nulling them.
    """
    if city is None:
        return None
    stripped = city.strip()
    if stripped.startswith("#"):
        return None
    normalised = stripped.lstrip("#").lower()
    if normalised in CITY_BLOCKLIST:
        return None
    # Single lowercase word with no spaces → likely a hashtag-derived token.
    # Try fuzzy correction before rejecting.
    if " " not in normalised and normalised.islower():
        if normalised in _KNOWN_CITIES:
            return _KNOWN_CITIES[normalised]
        matches = difflib.get_close_matches(normalised, _KNOWN_CITIES.keys(), n=1, cutoff=0.85)
        if matches:
            return _KNOWN_CITIES[matches[0]]
        return None
    return stripped or None
