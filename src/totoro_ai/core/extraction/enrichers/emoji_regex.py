"""Level 3 — emoji/hashtag regex candidate enricher."""

import re

from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
)

# Matches 📍PlaceName — captures text after 📍 up to comma, newline, or next 📍
_EMOJI_PATTERN = re.compile(r"📍([^📍,\n]+)")
# Matches @PlaceName — word characters (creator-tagged locations)
_AT_PATTERN = re.compile(r"@([A-Za-z0-9_]+)")
# Matches #hashtag — used as city hint when near a place candidate
_HASHTAG_PATTERN = re.compile(r"#([A-Za-z][A-Za-z0-9]*)")


class EmojiRegexEnricher:
    """Pure-regex candidate enricher for 📍 markers and @mentions (Level 3).

    No LLM calls, no external dependencies. Always appends to context.candidates
    and returns None (enricher contract).
    """

    async def enrich(self, context: ExtractionContext) -> None:
        """Find all 📍 and @ place markers in available text.

        Uses context.caption if set, otherwise context.supplementary_text.
        Returns immediately if neither is available.
        """
        text = context.caption or context.supplementary_text
        if not text:
            return

        # Extract city hint from first short standalone hashtag in the text
        hashtag_city = self._extract_city_hint(text)

        # Find all 📍PlaceName matches
        for match in _EMOJI_PATTERN.finditer(text):
            name = match.group(1).strip()
            if name:
                context.candidates.append(
                    CandidatePlace(
                        name=name,
                        city=hashtag_city,
                        cuisine=None,
                        source=ExtractionLevel.EMOJI_REGEX,
                    )
                )

        # Find all @PlaceName matches (creator-tagged locations)
        for match in _AT_PATTERN.finditer(text):
            name = match.group(1).strip()
            if name:
                context.candidates.append(
                    CandidatePlace(
                        name=name,
                        city=hashtag_city,
                        cuisine=None,
                        source=ExtractionLevel.EMOJI_REGEX,
                    )
                )

    @staticmethod
    def _extract_city_hint(text: str) -> str | None:
        """Extract the first plausible city hashtag from text.

        Returns the hashtag value if it looks like a city (alpha only, 3-20 chars).
        Returns None if no plausible city hashtag found.
        """
        for match in _HASHTAG_PATTERN.finditer(text):
            tag = match.group(1)
            if 3 <= len(tag) <= 20 and tag.isalpha():
                return tag
        return None
