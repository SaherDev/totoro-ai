"""Conversational food and dining advisor service."""

from typing import TYPE_CHECKING, cast

from totoro_ai.api.errors import LLMUnavailableError
from totoro_ai.providers.llm import get_llm
from totoro_ai.providers.tracing import get_langfuse_client

if TYPE_CHECKING:
    from totoro_ai.core.memory.service import UserMemoryService

_SYSTEM_PROMPT = """\
You are a knowledgeable food and dining advisor with deep expertise in global food \
culture, cuisines, restaurants, street food, and dining etiquette.

You give direct, opinionated answers. When asked for a recommendation, you make one \
— you don't list options without committing to a favourite. When asked a conceptual \
question (e.g. differences between dish types, whether an experience is worth it), \
you answer with a clear stance and practical reasoning — never "it depends" as a \
standalone answer.

When asked about etiquette, tipping, or food safety, lead with a clear yes or no, \
then explain. Do not hedge.

When asked how to find good places or spot tourist traps, give 2–3 specific, \
observable heuristics — not generic advice like "ask locals".

Your areas of expertise:
- Destination food scenes (cities, regions, neighbourhoods)
- Food culture and culinary knowledge (ingredients, techniques, dish types, cuisines)
- Dining etiquette and practical advice (tipping customs, street food safety, \
reservation norms)
- How to find good places and avoid tourist traps

Be conversational. Be specific. Avoid generic travel-guide language.\
"""


class ChatAssistantService:
    """Conversational food and dining advisor with user context injection.

    Takes a user message and returns a direct LLM response.
    No RAG, no vector search, no ranking.
    Injects user memories into the system prompt for personalized advice.
    """

    def __init__(self, memory_service: "UserMemoryService") -> None:
        """Initialize with memory service for context injection (ADR-010, ADR-038)."""
        self._llm = get_llm("chat_assistant")
        self._memory = memory_service

    async def run(self, message: str, user_id: str) -> str:
        """Run the chat assistant for a single message.

        Args:
            message: The user's question or request.
            user_id: Caller identity, used for Langfuse tracing.

        Returns:
            Conversational response string from the LLM.

        Raises:
            LLMUnavailableError: If the LLM call fails or times out.
        """
        # Load user memories for context injection (ADR-010)
        memory_list = await self._memory.load_memories(user_id)
        user_memories = "\n".join(memory_list) if memory_list else None

        lf = get_langfuse_client()
        generation = (
            lf.generation(
                name="chat_assistant",
                input={"user_id": user_id, "message": message},
            )
            if lf
            else None
        )

        # Build user message with memories injected (ADR-010, ADR-044)
        # Memories go in the user message for consistent behavior across models.
        context_parts: list[str] = []
        if user_memories:
            context_parts.append(f"User preferences:\n{user_memories}")
        if context_parts:
            user_content = "\n\n".join(context_parts) + f"\n\nQuestion: {message}"
        else:
            user_content = message

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            response = cast(str, await self._llm.complete(messages))
            if generation:
                generation.end(output={"response": response})
            return response
        except Exception as exc:
            if generation:
                generation.end(output={"error": str(exc)})
            raise LLMUnavailableError(str(exc)) from exc
