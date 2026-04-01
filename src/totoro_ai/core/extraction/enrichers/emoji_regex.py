"""Level 3 — Emoji and hashtag regex candidate enricher.

Finds ALL place markers in text: pin emoji, @ mentions, location hashtags.
Pure regex — no API calls, no cost, instant.
"""

import re

from totoro_ai.core.extraction.models import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
)

# Patterns for place markers in social media captions:
# 1. 📍/📌 followed by place name (capitalized words up to lowercase/punctuation break)
# 2. @ followed by capitalized word sequence (place-like, not @username)
# 3. CamelCase hashtags like #FujiRamen
_PIN_EMOJI_PATTERN = re.compile(r"[📍📌]\s*((?:[A-Z][A-Za-z0-9\-'&.]*\s*)+)")

# Hashtag pattern for location-specific tags like #FujiRamen or #BangkokEats
_HASHTAG_PLACE_PATTERN = re.compile(r"#([A-Z][a-z]+(?:[A-Z][a-z]+)+)")

# @ mention — capitalized word sequence (2+ words suggests a place, not a username)
_AT_PLACE_PATTERN = re.compile(
    r"@((?:[A-Z][A-Za-z0-9\-'&.]*\s+){1,}[A-Z][A-Za-z0-9\-'&.]*)"
)


class EmojiRegexEnricher:
    """Find ALL place markers via regex patterns.

    Operates on context.caption or context.supplementary_text.
    Each match becomes a CandidatePlace(source=EMOJI_REGEX).
    """

    async def enrich(self, context: ExtractionContext) -> None:
        text = context.caption or context.supplementary_text
        if not text:
            return

        found_names: set[str] = set()

        for pattern in [_PIN_EMOJI_PATTERN, _AT_PLACE_PATTERN, _HASHTAG_PLACE_PATTERN]:
            for match in pattern.finditer(text):
                name = match.group(1).strip()
                if name and len(name) >= 2 and name.lower() not in found_names:
                    found_names.add(name.lower())
                    context.candidates.append(
                        CandidatePlace(
                            name=name,
                            source=ExtractionLevel.EMOJI_REGEX,
                        )
                    )
