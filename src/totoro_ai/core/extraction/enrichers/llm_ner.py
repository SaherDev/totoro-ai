"""Level 4 — GPT-4o-mini NER candidate enricher.

Extracts ALL place names via LLM. NO skip guard — always runs
regardless of what earlier enrichers found. This ensures multi-place
inputs ("top 5 ramen in Tokyo") catch places regex missed.
"""

import logging

from pydantic import BaseModel, Field

from totoro_ai.core.extraction.models import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
)
from totoro_ai.providers.llm import InstructorClient

logger = logging.getLogger(__name__)


class ExtractedPlace(BaseModel):
    """Single place extracted by the LLM."""

    name: str = Field(description="Name of the place/restaurant/venue")
    city: str | None = Field(
        default=None, description="City where the place is located"
    )
    cuisine: str | None = Field(
        default=None, description="Cuisine type e.g. ramen, italian"
    )


class NERExtractionList(BaseModel):
    """LLM response model for multi-place extraction."""

    places: list[ExtractedPlace] = Field(
        description="ALL place names mentioned in the text"
    )


class LLMNEREnricher:
    """Extract ALL place names from text via GPT-4o-mini.

    No skip guard. Always runs for multi-place support.
    """

    def __init__(self, instructor_client: InstructorClient) -> None:
        self._instructor_client = instructor_client

    async def enrich(self, context: ExtractionContext) -> None:
        text = context.caption or context.supplementary_text
        if not text:
            return

        try:
            result = await self._instructor_client.extract(
                response_model=NERExtractionList,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract ALL place names (restaurants, "
                            "cafes, bars, venues) mentioned in the "
                            "text. Return every place as a separate "
                            "item. If the text mentions no places, "
                            "return an empty list."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Extract all place names from this text:\n\n{text}",
                    },
                ],
            )
        except Exception:
            logger.warning("LLM NER extraction failed", exc_info=True)
            return

        for place in result.places:
            if place.name and place.name.strip():
                context.candidates.append(
                    CandidatePlace(
                        name=place.name.strip(),
                        city=place.city,
                        cuisine=place.cuisine,
                        source=ExtractionLevel.LLM_NER,
                    )
                )
