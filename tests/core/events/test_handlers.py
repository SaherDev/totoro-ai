"""Unit tests for event handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from totoro_ai.core.config import MemoryConfidenceConfig
from totoro_ai.core.events.events import PersonalFactsExtracted
from totoro_ai.core.events.handlers import EventHandlers
from totoro_ai.core.memory.schemas import PersonalFact


class TestOnPersonalFactsExtracted:
    """Tests for EventHandlers.on_personal_facts_extracted().

    NOTE: Handler creates a fresh async session for background task execution,
    so unit tests mock the session factory and repository creation.
    """

    @pytest.fixture
    def mock_taste_service(self) -> MagicMock:
        """Create a mock TasteModelService."""
        return MagicMock()

    @pytest.fixture
    def mock_memory_service(self) -> MagicMock:
        """Create a mock UserMemoryService (used in non-background contexts)."""
        return MagicMock()

    @pytest.fixture
    def handlers(
        self, mock_taste_service: MagicMock, mock_memory_service: MagicMock
    ) -> EventHandlers:
        """Create EventHandlers with mocked dependencies."""
        return EventHandlers(
            taste_service=mock_taste_service,
            memory_service=mock_memory_service,
            langfuse=None,
        )

    @pytest.mark.asyncio
    async def test_empty_facts_skips_save(
        self, handlers: EventHandlers
    ) -> None:
        """on_personal_facts_extracted skips when personal_facts is empty."""
        event = PersonalFactsExtracted(user_id="user-1", personal_facts=[])

        await handlers.on_personal_facts_extracted(event)
        # No exception raised, handler returns early

    @pytest.mark.asyncio
    async def test_calls_memory_service_save_facts(self, handlers: EventHandlers) -> None:
        """on_personal_facts_extracted creates fresh session and calls save_facts."""
        with patch(
            "totoro_ai.core.memory.repository.SQLAlchemyUserMemoryRepository"
        ) as MockRepository, patch(
            "totoro_ai.core.memory.service.UserMemoryService"
        ) as MockService:
            mock_repo = AsyncMock()
            mock_service = AsyncMock()
            mock_service.save_facts = AsyncMock()
            MockRepository.return_value = mock_repo
            MockService.return_value = mock_service

            with patch(
                "sqlalchemy.ext.asyncio.async_sessionmaker"
            ) as mock_factory:
                mock_session = AsyncMock()
                mock_factory.return_value.return_value.__aenter__.return_value = (
                    mock_session
                )

                event = PersonalFactsExtracted(
                    user_id="user-1",
                    personal_facts=[
                        PersonalFact(text="I'm vegetarian", source="stated")
                    ],
                )

                await handlers.on_personal_facts_extracted(event)

                # Verify UserMemoryService was instantiated with the repository
                MockService.assert_called_once_with(repo=mock_repo)
                # Verify save_facts was called
                mock_service.save_facts.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_user_id(self, handlers: EventHandlers) -> None:
        """on_personal_facts_extracted passes correct user_id."""
        with patch(
            "totoro_ai.core.memory.repository.SQLAlchemyUserMemoryRepository"
        ) as MockRepository, patch(
            "totoro_ai.core.memory.service.UserMemoryService"
        ) as MockService:
            mock_repo = AsyncMock()
            mock_service = AsyncMock()
            mock_service.save_facts = AsyncMock()
            MockRepository.return_value = mock_repo
            MockService.return_value = mock_service

            with patch(
                "sqlalchemy.ext.asyncio.async_sessionmaker"
            ) as mock_factory:
                mock_session = AsyncMock()
                mock_factory.return_value.return_value.__aenter__.return_value = (
                    mock_session
                )

                event = PersonalFactsExtracted(
                    user_id="user-123",
                    personal_facts=[PersonalFact(text="I'm vegan", source="stated")],
                )

                await handlers.on_personal_facts_extracted(event)

                call_args = mock_service.save_facts.call_args
                assert call_args[1]["user_id"] == "user-123"

    @pytest.mark.asyncio
    async def test_passes_personal_facts(self, handlers: EventHandlers) -> None:
        """on_personal_facts_extracted passes correct personal_facts list."""
        with patch(
            "totoro_ai.core.memory.repository.SQLAlchemyUserMemoryRepository"
        ) as MockRepository, patch(
            "totoro_ai.core.memory.service.UserMemoryService"
        ) as MockService:
            mock_repo = AsyncMock()
            mock_service = AsyncMock()
            mock_service.save_facts = AsyncMock()
            MockRepository.return_value = mock_repo
            MockService.return_value = mock_service

            with patch(
                "sqlalchemy.ext.asyncio.async_sessionmaker"
            ) as mock_factory:
                mock_session = AsyncMock()
                mock_factory.return_value.return_value.__aenter__.return_value = (
                    mock_session
                )

                facts = [
                    PersonalFact(text="I'm vegetarian", source="stated"),
                    PersonalFact(text="I hate seafood", source="inferred"),
                ]
                event = PersonalFactsExtracted(user_id="user-1", personal_facts=facts)

                await handlers.on_personal_facts_extracted(event)

                call_args = mock_service.save_facts.call_args
                assert call_args[1]["facts"] == facts

    @pytest.mark.asyncio
    async def test_passes_confidence_config(self, handlers: EventHandlers) -> None:
        """on_personal_facts_extracted passes confidence_config from app config."""
        with patch(
            "totoro_ai.core.memory.repository.SQLAlchemyUserMemoryRepository"
        ) as MockRepository, patch(
            "totoro_ai.core.memory.service.UserMemoryService"
        ) as MockService:
            mock_repo = AsyncMock()
            mock_service = AsyncMock()
            mock_service.save_facts = AsyncMock()
            MockRepository.return_value = mock_repo
            MockService.return_value = mock_service

            with patch(
                "sqlalchemy.ext.asyncio.async_sessionmaker"
            ) as mock_factory:
                mock_session = AsyncMock()
                mock_factory.return_value.return_value.__aenter__.return_value = (
                    mock_session
                )

                event = PersonalFactsExtracted(
                    user_id="user-1",
                    personal_facts=[
                        PersonalFact(text="I'm vegetarian", source="stated")
                    ],
                )

                await handlers.on_personal_facts_extracted(event)

                call_args = mock_service.save_facts.call_args
                confidence_config = call_args[1]["confidence_config"]
                assert isinstance(confidence_config, MemoryConfidenceConfig)
                assert confidence_config.stated == 0.9
                assert confidence_config.inferred == 0.6

    @pytest.mark.asyncio
    async def test_catches_exception_does_not_raise(self, handlers: EventHandlers) -> None:
        """on_personal_facts_extracted catches exceptions and does not raise."""
        with patch(
            "totoro_ai.core.memory.repository.SQLAlchemyUserMemoryRepository"
        ) as MockRepository, patch(
            "totoro_ai.core.memory.service.UserMemoryService"
        ) as MockService:
            mock_repo = AsyncMock()
            mock_service = AsyncMock()
            mock_service.save_facts = AsyncMock(side_effect=Exception("DB error"))
            MockRepository.return_value = mock_repo
            MockService.return_value = mock_service

            with patch(
                "sqlalchemy.ext.asyncio.async_sessionmaker"
            ) as mock_factory:
                mock_session = AsyncMock()
                mock_factory.return_value.return_value.__aenter__.return_value = (
                    mock_session
                )

                event = PersonalFactsExtracted(
                    user_id="user-1",
                    personal_facts=[
                        PersonalFact(text="I'm vegetarian", source="stated")
                    ],
                )

                # Should not raise
                await handlers.on_personal_facts_extracted(event)

    @pytest.mark.asyncio
    async def test_exception_on_empty_facts_does_nothing(
        self, handlers: EventHandlers
    ) -> None:
        """on_personal_facts_extracted with empty facts does nothing (no exception)."""
        event = PersonalFactsExtracted(user_id="user-1", personal_facts=[])

        # Should not raise
        await handlers.on_personal_facts_extracted(event)
