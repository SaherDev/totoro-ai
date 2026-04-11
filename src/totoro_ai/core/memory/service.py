"""User memory service — sole consumer of UserMemoryRepository (ADR-038)."""

from totoro_ai.core.config import MemoryConfidenceConfig
from totoro_ai.core.memory.repository import UserMemoryRepository
from totoro_ai.core.memory.schemas import PersonalFact


class UserMemoryService:
    """Single consumer of UserMemoryRepository.

    All other components (ChatService, EventHandlers) use this service —
    never touch the repository implementation directly.

    Access constraint (ADR-038): SQLAlchemyUserMemoryRepository is instantiated
    only inside api/deps.py get_user_memory_service(). No other dependency
    function or module constructs it.
    """

    def __init__(self, repo: UserMemoryRepository) -> None:
        self.repo = repo

    async def save_facts(
        self,
        user_id: str,
        facts: list[PersonalFact],
        confidence_config: MemoryConfidenceConfig,
    ) -> None:
        """Persist extracted personal facts.

        Skips write if facts list is empty.
        Assigns confidence from config by source: stated=0.9, inferred=0.6.
        Duplicate rows silently skipped by database UNIQUE constraint.

        Args:
            user_id: User identity
            facts: list of extracted PersonalFact objects
            confidence_config: config with stated and inferred thresholds
        """
        if not facts:
            return

        for fact in facts:
            confidence = (
                confidence_config.stated
                if fact.source == "stated"
                else confidence_config.inferred
            )
            await self.repo.save(
                user_id=user_id,
                memory=fact.text,
                source=fact.source,
                confidence=confidence,
            )

    async def load_memories(self, user_id: str) -> list[str]:
        """Load all stored memory strings for user_id.

        Returns [] on failure — never raises.
        Swallows repository exceptions and returns empty list.

        Args:
            user_id: User identity

        Returns:
            list[str]: Plain text memory strings, or [] on failure
        """
        try:
            return await self.repo.load(user_id)
        except Exception:
            return []
