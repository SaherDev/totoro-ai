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
You are an intent classifier for a food and dining app. Classify the user message into exactly one of these intents:

- extract-place: The user is sharing a TikTok URL, Instagram URL, or any social-media link that contains a place to save.
- consult: The user wants a place recommendation — e.g. "cheap dinner nearby", "best ramen in Bangkok", "where should I eat tonight?".
- recall: The user wants to find or retrieve a place they previously saved — e.g. "that ramen place I saved", "show me saved Thai restaurants", "find the place from my list".
- assistant: The user is asking a general food or dining question with no clear intent to save or retrieve — e.g. "is tipping expected in Japan?", "what's the difference between pad see ew and pad thai?".

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
