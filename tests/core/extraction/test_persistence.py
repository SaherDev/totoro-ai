"""Tests for ExtractionPersistenceService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.core.events.events import PlaceSaved
from totoro_ai.core.extraction.persistence import ExtractionPersistenceService
from totoro_ai.core.extraction.types import ExtractionLevel, ExtractionResult


def _make_result(
    place_name: str = "Fuji Ramen",
    address: str | None = "123 Sukhumvit",
    city: str | None = "Bangkok",
    cuisine: str | None = "ramen",
    confidence: float = 0.87,
    resolved_by: ExtractionLevel = ExtractionLevel.LLM_NER,
    external_id: str | None = "place_123",
    external_provider: str | None = "google",
) -> ExtractionResult:
    return ExtractionResult(
        place_name=place_name,
        address=address,
        city=city,
        cuisine=cuisine,
        confidence=confidence,
        resolved_by=resolved_by,
        corroborated=False,
        external_provider=external_provider,
        external_id=external_id,
    )


@pytest.fixture
def place_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_provider = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    return repo


@pytest.fixture
def embedding_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.bulk_upsert_embeddings = AsyncMock()
    return repo


@pytest.fixture
def embedder() -> AsyncMock:
    e = AsyncMock()
    e.embed = AsyncMock(return_value=[[0.1] * 1024])
    return e


@pytest.fixture
def event_dispatcher() -> AsyncMock:
    d = AsyncMock()
    d.dispatch = AsyncMock()
    return d


@pytest.fixture
def service(
    place_repo: AsyncMock,
    embedding_repo: AsyncMock,
    embedder: AsyncMock,
    event_dispatcher: AsyncMock,
) -> ExtractionPersistenceService:
    return ExtractionPersistenceService(
        place_repo=place_repo,
        embedding_repo=embedding_repo,
        embedder=embedder,
        event_dispatcher=event_dispatcher,
    )


# ---------------------------------------------------------------------------
# New place — write + dispatch + embed
# ---------------------------------------------------------------------------


async def test_new_place_is_saved_and_place_saved_dispatched(
    service: ExtractionPersistenceService,
    place_repo: AsyncMock,
    event_dispatcher: AsyncMock,
) -> None:
    """A new place with external_id is saved and PlaceSaved dispatched."""
    result = _make_result()

    saved_ids = await service.save_and_emit([result], user_id="user-1")

    assert len(saved_ids) == 1
    place_repo.save.assert_awaited_once()
    event_dispatcher.dispatch.assert_awaited_once()
    dispatched: PlaceSaved = event_dispatcher.dispatch.call_args[0][0]
    assert dispatched.place_ids == saved_ids
    assert dispatched.user_id == "user-1"


async def test_returns_list_of_place_id_strings(
    service: ExtractionPersistenceService,
    place_repo: AsyncMock,
) -> None:
    """save_and_emit returns list of UUID strings for saved places."""
    saved_ids = await service.save_and_emit([_make_result()], user_id="user-1")

    assert isinstance(saved_ids, list)
    assert len(saved_ids) == 1
    assert isinstance(saved_ids[0], str)
    assert len(saved_ids[0]) > 0


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


async def test_duplicate_place_is_skipped(
    service: ExtractionPersistenceService,
    place_repo: AsyncMock,
    event_dispatcher: AsyncMock,
) -> None:
    """When existing place found by provider+external_id, skip it."""
    existing = MagicMock()
    existing.id = "existing-uuid"
    place_repo.get_by_provider = AsyncMock(return_value=existing)

    saved_ids = await service.save_and_emit([_make_result()], user_id="user-1")

    assert saved_ids == []
    place_repo.save.assert_not_awaited()


async def test_all_duplicates_no_place_saved_event(
    service: ExtractionPersistenceService,
    place_repo: AsyncMock,
    event_dispatcher: AsyncMock,
) -> None:
    """When all candidates are duplicates, PlaceSaved is NOT dispatched."""
    existing = MagicMock()
    existing.id = "existing-uuid"
    place_repo.get_by_provider = AsyncMock(return_value=existing)

    saved_ids = await service.save_and_emit(
        [_make_result("Place A"), _make_result("Place B")], user_id="user-1"
    )

    assert saved_ids == []
    event_dispatcher.dispatch.assert_not_awaited()


async def test_external_id_none_skips_dedup_check(
    service: ExtractionPersistenceService,
    place_repo: AsyncMock,
) -> None:
    """When external_id is None, no dedup check is performed, place is saved."""
    result = _make_result(external_id=None, external_provider=None)

    saved_ids = await service.save_and_emit([result], user_id="user-1")

    place_repo.get_by_provider.assert_not_awaited()
    assert len(saved_ids) == 1


# ---------------------------------------------------------------------------
# Batch embedding
# ---------------------------------------------------------------------------


async def test_single_place_calls_bulk_upsert_with_one_record(
    service: ExtractionPersistenceService,
    embedding_repo: AsyncMock,
    embedder: AsyncMock,
) -> None:
    """Single place → embedder called with 1 text, bulk_upsert_embeddings called with 1 record."""  # noqa: E501
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024])

    await service.save_and_emit([_make_result()], user_id="user-1")

    embedder.embed.assert_awaited_once()
    texts = embedder.embed.call_args[0][0]
    assert len(texts) == 1

    embedding_repo.bulk_upsert_embeddings.assert_awaited_once()
    records = embedding_repo.bulk_upsert_embeddings.call_args[0][0]
    assert len(records) == 1


async def test_multi_place_calls_bulk_upsert_with_all_records(
    service: ExtractionPersistenceService,
    embedding_repo: AsyncMock,
    embedder: AsyncMock,
) -> None:
    """5 places → one embed call with 5 texts, one bulk_upsert_embeddings call with 5 records."""  # noqa: E501
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024] * 5)
    results = [_make_result(f"Place {i}", external_id=f"ext_{i}") for i in range(5)]

    # Make dedup return None for all (no duplicates)
    saved_ids = await service.save_and_emit(results, user_id="user-1")

    assert len(saved_ids) == 5
    texts = embedder.embed.call_args[0][0]
    assert len(texts) == 5
    embedder.embed.assert_awaited_once()

    embedding_repo.bulk_upsert_embeddings.assert_awaited_once()
    records = embedding_repo.bulk_upsert_embeddings.call_args[0][0]
    assert len(records) == 5


async def test_embedding_failure_is_non_fatal(
    service: ExtractionPersistenceService,
    embedding_repo: AsyncMock,
    event_dispatcher: AsyncMock,
) -> None:
    """If bulk_upsert_embeddings raises RuntimeError, place is still saved and IDs returned."""  # noqa: E501
    embedding_repo.bulk_upsert_embeddings = AsyncMock(
        side_effect=RuntimeError("DB error")
    )

    saved_ids = await service.save_and_emit([_make_result()], user_id="user-1")

    assert len(saved_ids) == 1
    event_dispatcher.dispatch.assert_awaited_once()


# ---------------------------------------------------------------------------
# Ordering invariant: DB writes → dispatch → embeddings
# ---------------------------------------------------------------------------


async def test_place_saved_dispatched_before_embeddings(
    service: ExtractionPersistenceService,
    event_dispatcher: AsyncMock,
    embedding_repo: AsyncMock,
) -> None:
    """PlaceSaved must be dispatched AFTER DB writes, BEFORE bulk_upsert_embeddings."""
    call_order: list[str] = []

    async def dispatch_side_effect(event: object) -> None:
        call_order.append("dispatch")

    async def embed_side_effect(records: list) -> None:
        call_order.append("embed_bulk")

    event_dispatcher.dispatch = AsyncMock(side_effect=dispatch_side_effect)
    embedding_repo.bulk_upsert_embeddings = AsyncMock(side_effect=embed_side_effect)

    await service.save_and_emit([_make_result()], user_id="user-1")

    assert call_order == ["dispatch", "embed_bulk"]


# ---------------------------------------------------------------------------
# Multi-place: one PlaceSaved with all IDs
# ---------------------------------------------------------------------------


async def test_multiple_places_one_place_saved_event_with_all_ids(
    service: ExtractionPersistenceService,
    event_dispatcher: AsyncMock,
    embedder: AsyncMock,
) -> None:
    """Multiple new places → one PlaceSaved event with all place_ids."""
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
    results = [
        _make_result("Place A", external_id="ext_a"),
        _make_result("Place B", external_id="ext_b"),
    ]

    saved_ids = await service.save_and_emit(results, user_id="user-1")

    event_dispatcher.dispatch.assert_awaited_once()
    event: PlaceSaved = event_dispatcher.dispatch.call_args[0][0]
    assert set(event.place_ids) == set(saved_ids)
    assert len(event.place_ids) == 2
