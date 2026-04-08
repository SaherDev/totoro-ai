"""Shared city sanitisation used by emoji_regex and llm_ner enrichers."""

# Words that are never valid city names — content tags, topic labels, and common
# false positives produced by both regex and LLM city extraction.
CITY_BLOCKLIST: frozenset[str] = frozenset(
    {
        "mall",
        "paragon",
        "shoppingmall",
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
    }
)


def sanitize_city(city: str | None) -> str | None:
    """Return None if city is a hashtag token or a known non-city label."""
    if city is None:
        return None
    stripped = city.strip()
    if stripped.startswith("#"):
        return None
    if stripped.lstrip("#").lower() in CITY_BLOCKLIST:
        return None
    return stripped or None
