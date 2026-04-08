"""Shared city sanitisation used by emoji_regex and llm_ner enrichers."""

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

# Single-word lowercase values not in this set are treated as hashtag-derived
# tokens and rejected — they are neighbourhood tags, not city names.
_KNOWN_CITIES: frozenset[str] = frozenset(
    {
        "bangkok",
        "london",
        "tokyo",
        "paris",
        "singapore",
        "kualalumpur",
        "seoul",
        "jakarta",
    }
)


def sanitize_city(city: str | None) -> str | None:
    """Return None if city is a hashtag token or a known non-city label."""
    if city is None:
        return None
    stripped = city.strip()
    if stripped.startswith("#"):
        return None
    normalised = stripped.lstrip("#").lower()
    if normalised in CITY_BLOCKLIST:
        return None
    # Single lowercase word with no spaces → likely a hashtag-derived token;
    # accept only if it matches a known real city name.
    if " " not in normalised and normalised.islower():
        if normalised not in _KNOWN_CITIES:
            return None
    return stripped or None
