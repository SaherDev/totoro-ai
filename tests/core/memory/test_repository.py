"""Unit tests for UserMemoryRepository implementations."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from totoro_ai.core.memory.repository import (
    NullUserMemoryRepository,
    SQLAlchemyUserMemoryRepository,
)


class TestNullUserMemoryRepository:
    """Tests for NullUserMemoryRepository (no-op implementation)."""

    @pytest.mark.asyncio
    async def test_save_noop(self) -> None:
        """NullUserMemoryRepository.save() is a no-op."""
        repo = NullUserMemoryRepository()
        # Should not raise
        await repo.save(
            user_id="user-1",
            memory="I use a wheelchair",
            source="stated",
            confidence=0.9,
        )

    @pytest.mark.asyncio
    async def test_load_returns_empty_list(self) -> None:
        """NullUserMemoryRepository.load() always returns []."""
        repo = NullUserMemoryRepository()
        result = await repo.load("user-1")
        assert result == []


class TestSQLAlchemyUserMemoryRepository:
    """Tests for SQLAlchemyUserMemoryRepository (SQLAlchemy async impl)."""

    @pytest.fixture
    def mock_session(self) -> MagicMock:
        """Create a mock AsyncSession."""
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_session: MagicMock) -> SQLAlchemyUserMemoryRepository:
        """Create repository instance with mocked session."""
        return SQLAlchemyUserMemoryRepository(mock_session)

    @pytest.mark.asyncio
    async def test_save_calls_execute(
        self, repo: SQLAlchemyUserMemoryRepository, mock_session: MagicMock
    ) -> None:
        """save() calls session.execute() and commit() with insert statement."""
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        await repo.save(
            user_id="user-1",
            memory="I use a wheelchair",
            source="stated",
            confidence=0.9,
        )

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_success(
        self, repo: SQLAlchemyUserMemoryRepository, mock_session: MagicMock
    ) -> None:
        """load() returns list of strings from database."""
        mock_result = MagicMock()
        mock_result.all.return_value = [("I use a wheelchair",), ("I'm vegetarian",)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await repo.load("user-1")

        assert result == ["I use a wheelchair", "I'm vegetarian"]

    @pytest.mark.asyncio
    async def test_load_catches_exception_returns_empty_list(
        self, repo: SQLAlchemyUserMemoryRepository, mock_session: MagicMock
    ) -> None:
        """load() catches exceptions and returns []."""
        mock_session.execute = AsyncMock(side_effect=Exception("DB error"))

        result = await repo.load("user-1")

        assert result == []

    @pytest.mark.asyncio
    async def test_load_empty_result(
        self, repo: SQLAlchemyUserMemoryRepository, mock_session: MagicMock
    ) -> None:
        """load() returns [] when database has no results."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await repo.load("user-1")

        assert result == []
