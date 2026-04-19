"""Intent classification for the unified chat router (ADR-016)."""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, ValidationError

from totoro_ai.core.memory.schemas import PersonalFact
from totoro_ai.providers.llm import get_llm
from totoro_ai.providers.tracing import get_langfuse_client

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an intent classifier for a place recommendation app. The app helps users save and discover ALL kinds of places — restaurants, cafes, bars, hotels, hostels, museums, parks, galleries, shops, boutiques, markets, bookstores, gyms, spas, co-working spaces, and more — not just food venues. Classify the user message into exactly one of these intents:

- extract-place: The user is sharing or recommending a specific place — this includes URLs (TikTok, Instagram, Reddit, Google Maps, etc.) AND plain-text mentions of a named place with positive sentiment or a desire to save it. Examples: "RAMEN KAISUGI Bangkok is incredible", "you have to try Nara Eatery", "The Louvre is amazing", "this hotel in Ubud is beautiful", "save this bookstore: Shakespeare & Co", "just visited the Kyoto National Museum, stunning". ANY message that contains a URL should be extract-place unless clearly unrelated to a venue. IMPORTANT: if the user refers to something they already saved in the past (past tense "I saved", "I bookmarked"), classify as recall, not extract-place.
- consult: The user wants a place recommendation but has NOT named a specific place — e.g. "cheap dinner nearby", "nice boutique hotel near the beach", "things to do with kids in Kyoto", "best ramen in Bangkok", "a quiet museum for a rainy afternoon". STRONG SIGNAL: any message containing proximity words ("nearby", "near me", "around here", "close by") or activity types ("dinner", "lunch", "breakfast", "brunch", "coffee", "drinks", "shopping", "stay", "hotel", "museum", "park", "things to do") combined with any descriptor (even unfamiliar slang or adjectives) should be consult. When in doubt between consult and assistant, choose consult.
- recall: The user wants to find or retrieve a place they previously saved — e.g. "that ramen place I saved", "that boutique from Instagram", "show me saved hotels in Paris", "find the museum from my list". Key signal: past tense references to saving ("I saved", "I bookmarked", "from my saves").
- assistant: The user is asking a general question with no clear intent to save or retrieve a specific place — e.g. "is tipping expected in Japan?", "what's the difference between pad see ew and pad thai?", "are museums free on Sundays?", "do hostels in Portugal accept walk-ins?".

ALSO extract personal facts about the user from the message:
- Extract only declarative user facts (first-person statements about the user's own preferences, needs, or characteristics).
- Example: "I use a wheelchair", "I'm vegetarian", "I hate seafood".
- NEVER extract place attributes. Example: "This place is wheelchair-friendly" must NOT be included.
- If no personal facts are present, return an empty array.

Respond ONLY with a JSON object in this exact format:
{
  "intent": "<intent>",
  "confidence": <0.0-1.0>,
  "clarification_needed": <true|false>,
  "clarification_question": "<single short question or null>",
  "personal_facts": [
    {"text": "<fact>", "source": "stated"}
  ]
}

Rules:
- If the message contains "nearby", "near me", "around here", or any activity word ("dinner", "lunch", "breakfast", "coffee", "drinks", "hotel", "museum", "park", "shop", "gym", "spa"), classify as consult unless there is a clear URL or explicit past-tense save reference.
- confidence < 0.7 means clarification_needed must be true
- clarification_question must be exactly one short, conversational question when clarification_needed is true, otherwise null
- personal_facts is an array of objects with "text" (string) and "source" (always "stated" — user explicitly said it)
- personal_facts may be an empty array [] if no facts are present
- Never include explanation outside the JSON object\
"""

_MARKDOWN_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")


class IntentClassification(BaseModel):
    """Output of intent classification — never crosses the API boundary."""

    intent: str
    confidence: float
    clarification_needed: bool
    clarification_question: str | None = None
    personal_facts: list[PersonalFact] = []


def _strip_markdown_fences(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` wrappers if present."""
    match = _MARKDOWN_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


async def classify_intent(message: str) -> IntentClassification:
    """Classify user message intent using the intent_router LLM role.

    Args:
        message: Raw user message text.

    Returns:
        IntentClassification with intent, confidence, and optional clarification.

    Raises:
        ValidationError: If LLM response cannot be parsed after one retry.
    """
    llm = get_llm("intent_router")
    lf = get_langfuse_client()

    generation = (
        lf.generation(
            name="intent_router",
            input={"message": message},
        )
        if lf
        else None
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]

    try:
        raw = await llm.complete(messages)

        if generation:
            generation.end(output={"raw": raw})

        try:
            return IntentClassification.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError):
            # Groq occasionally adds markdown fences — strip and retry once
            cleaned = _strip_markdown_fences(raw)
            return IntentClassification.model_validate_json(cleaned)

    except (ValidationError, json.JSONDecodeError):
        raise
    except Exception as exc:
        if generation:
            generation.end(output={"error": str(exc)})
        raise
