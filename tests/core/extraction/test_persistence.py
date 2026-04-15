"""Tests for ExtractionPersistenceService (ADR-054 / feature 019).

The persistence service now goes through `PlacesService.create_batch` and
receives `ValidatedCandidate` wrappers (not the removed `ExtractionResult`).
`DuplicatePlaceError` is the signal for "already in DB" — the service
retries conflicting rows one by one so successful rows are not lost.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from totoro_ai.core.events.events import PlaceSaved
from totoro_ai.core.extraction.persistence import (
    ExtractionPersistenceService,
    PlaceSaveOutcome,
)
from totoro_ai.core.extraction.types import ExtractionLevel, ValidatedCandidate
from totoro_ai.core.places import (
    DuplicatePlaceError,
    DuplicateProviderId,
    PlaceAttributes,
    PlaceCreate,
    PlaceObject,
    PlaceProvider,
    PlaceType,
)

# ---------------------------------------------------------------------------
# factories
# ---------------------------------------------------------------------------


def _make_place_create(
    place_name: str = "Fuji Ramen",
    external_id: str | None = "place_123",
    provider: PlaceProvider | None = PlaceProvider.google,
    cuisine: str | None = "ramen",
    user_id: str = "user-1",
) -> PlaceCreate:
    return PlaceCreate(
        user_id=user_id,
        place_name=place_name,
        place_type=PlaceType.food_and_drink,
        subcategory="restaurant",
        attributes=PlaceAttributes(cuisine=cuisine),
        provider=provider,
        external_id=external_id,
    )


def _make_validated(
    place_name: str = "Fuji Ramen",
    confidence: float = 0.87,
    resolved_by: ExtractionLevel = ExtractionLevel.LLM_NER,
    external_id: str | None = "place_123",
    provider: PlaceProvider | None = PlaceProvider.google,
    cuisine: str | None = "ramen",
    user_id: str = "user-1",
) -> ValidatedCandidate:
    return ValidatedCandidate(
        place=_make_place_create(
            place_name=place_name,
            external_id=external_id,
            provider=provider,
            cuisine=cuisine,
            user_id=user_id,
        ),
        confidence=confidence,
        resolved_by=resolved_by,
        corroborated=False,
    )


def _make_saved_object(
    place_id: str,
    place_name: str = "Fuji Ramen",
    provider_id: str | None = "google:place_123",
) -> PlaceObject:
    return PlaceObject(
        place_id=place_id,
        place_name=place_name,
        place_type=PlaceType.food_and_drink,
        subcategory="restaurant",
        attributes=PlaceAttributes(cuisine="ramen"),
        provider_id=provider_id,
    )


@pytest.fixture
def places_service() -> AsyncMock:
    svc = AsyncMock()
    svc.create_batch = AsyncMock()
    svc.create = AsyncMock()
    svc.get = AsyncMock()
    return svc


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
    places_service: AsyncMock,
    embedding_repo: AsyncMock,
    embedder: AsyncMock,
    event_dispatcher: AsyncMock,
) -> ExtractionPersistenceService:
    return ExtractionPersistenceService(
        places_service=places_service,
        embedding_repo=embedding_repo,
        embedder=embedder,
        event_dispatcher=event_dispatcher,
    )


# ---------------------------------------------------------------------------
# Happy path — create_batch succeeds
# ---------------------------------------------------------------------------


async def test_new_place_is_saved_and_place_saved_dispatched(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    event_dispatcher: AsyncMock,
) -> None:
    places_service.create_batch.return_value = [_make_saved_object("place-1")]

    outcomes = await service.save_and_emit([_make_validated()], user_id="user-1")

    assert len(outcomes) == 1
    assert outcomes[0].status == "saved"
    assert outcomes[0].place_id == "place-1"
    places_service.create_batch.assert_awaited_once()
    event_dispatcher.dispatch.assert_awaited_once()
    dispatched: PlaceSaved = event_dispatcher.dispatch.call_args[0][0]
    assert dispatched.place_ids == ["place-1"]
    assert dispatched.user_id == "user-1"


async def test_returns_list_of_outcomes(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
) -> None:
    places_service.create_batch.return_value = [_make_saved_object("place-1")]

    outcomes = await service.save_and_emit([_make_validated()], user_id="user-1")

    assert isinstance(outcomes, list)
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], PlaceSaveOutcome)
    assert isinstance(outcomes[0].place_id, str)
    assert len(outcomes[0].place_id) > 0


# ---------------------------------------------------------------------------
# Duplicate handling — via DuplicatePlaceError from PlacesService
# ---------------------------------------------------------------------------


async def test_all_duplicates_marked_and_no_place_saved_event(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    event_dispatcher: AsyncMock,
) -> None:
    """When create_batch raises DuplicatePlaceError listing every row, all
    outcomes are marked "duplicate" and PlaceSaved is NOT dispatched."""
    vcs = [
        _make_validated("Place A", external_id="ext_a"),
        _make_validated("Place B", external_id="ext_b"),
    ]
    places_service.create_batch.side_effect = DuplicatePlaceError(
        [
            DuplicateProviderId(
                provider_id="google:ext_a", existing_place_id="existing-a"
            ),
            DuplicateProviderId(
                provider_id="google:ext_b", existing_place_id="existing-b"
            ),
        ]
    )
    places_service.get.side_effect = [
        _make_saved_object("existing-a", "Place A", "google:ext_a"),
        _make_saved_object("existing-b", "Place B", "google:ext_b"),
    ]

    outcomes = await service.save_and_emit(vcs, user_id="user-1")

    assert all(o.status == "duplicate" for o in outcomes)
    assert {o.place_id for o in outcomes} == {"existing-a", "existing-b"}
    event_dispatcher.dispatch.assert_not_awaited()


async def test_partial_duplicate_retries_one_by_one(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    event_dispatcher: AsyncMock,
) -> None:
    """When only some rows are duplicates, non-conflicting rows are retried
    via create() so successful rows are not lost."""
    vcs = [
        _make_validated("Place A", external_id="ext_a"),
        _make_validated("Place B", external_id="ext_b"),
    ]
    places_service.create_batch.side_effect = DuplicatePlaceError(
        [
            DuplicateProviderId(
                provider_id="google:ext_b", existing_place_id="existing-b"
            )
        ]
    )
    # Retry loop: B is looked up as duplicate; A is re-created successfully.
    places_service.get.return_value = _make_saved_object(
        "existing-b", "Place B", "google:ext_b"
    )
    places_service.create.return_value = _make_saved_object(
        "new-a", "Place A", "google:ext_a"
    )

    outcomes = await service.save_and_emit(vcs, user_id="user-1")

    statuses = [o.status for o in outcomes]
    assert statuses == ["saved", "duplicate"]
    assert outcomes[0].place_id == "new-a"
    assert outcomes[1].place_id == "existing-b"


async def test_external_id_none_passes_through_create_batch(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
) -> None:
    """When external_id is None, no namespace collision is possible; the
    row is just saved with provider_id=NULL."""
    places_service.create_batch.return_value = [
        _make_saved_object("place-1", provider_id=None)
    ]

    vc = _make_validated(external_id=None, provider=None)
    outcomes = await service.save_and_emit([vc], user_id="user-1")

    places_service.create_batch.assert_awaited_once()
    assert outcomes[0].status == "saved"


# ---------------------------------------------------------------------------
# Confidence threshold — below_threshold
# ---------------------------------------------------------------------------


async def test_below_threshold_is_not_saved(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    event_dispatcher: AsyncMock,
) -> None:
    """Confidence below save_threshold (0.70) is not written to DB."""
    vc = _make_validated(confidence=0.69)

    outcomes = await service.save_and_emit([vc], user_id="user-1")

    assert outcomes[0].status == "below_threshold"
    assert outcomes[0].place_id is None
    places_service.create_batch.assert_not_awaited()
    event_dispatcher.dispatch.assert_not_awaited()


async def test_at_threshold_is_saved(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
) -> None:
    """Confidence exactly at save_threshold (0.70) is saved."""
    places_service.create_batch.return_value = [_make_saved_object("place-1")]
    vc = _make_validated(confidence=0.70)

    outcomes = await service.save_and_emit([vc], user_id="user-1")

    assert outcomes[0].status == "saved"
    places_service.create_batch.assert_awaited_once()


async def test_all_below_threshold_no_place_saved_event(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    event_dispatcher: AsyncMock,
) -> None:
    outcomes = await service.save_and_emit(
        [
            _make_validated("A", confidence=0.50, external_id="ext_a"),
            _make_validated("B", confidence=0.60, external_id="ext_b"),
        ],
        user_id="user-1",
    )

    assert all(o.status == "below_threshold" for o in outcomes)
    places_service.create_batch.assert_not_awaited()
    event_dispatcher.dispatch.assert_not_awaited()


# ---------------------------------------------------------------------------
# Batch embedding
# ---------------------------------------------------------------------------


async def test_single_place_calls_bulk_upsert_with_one_record(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    embedding_repo: AsyncMock,
    embedder: AsyncMock,
) -> None:
    places_service.create_batch.return_value = [_make_saved_object("place-1")]
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024])

    await service.save_and_emit([_make_validated()], user_id="user-1")

    embedder.embed.assert_awaited_once()
    texts = embedder.embed.call_args[0][0]
    assert len(texts) == 1

    embedding_repo.bulk_upsert_embeddings.assert_awaited_once()
    records = embedding_repo.bulk_upsert_embeddings.call_args[0][0]
    assert len(records) == 1


async def test_multi_place_calls_bulk_upsert_with_all_records(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    embedding_repo: AsyncMock,
    embedder: AsyncMock,
) -> None:
    places_service.create_batch.return_value = [
        _make_saved_object(f"place-{i}", f"Place {i}") for i in range(5)
    ]
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024] * 5)
    vcs = [_make_validated(f"Place {i}", external_id=f"ext_{i}") for i in range(5)]

    outcomes = await service.save_and_emit(vcs, user_id="user-1")

    assert len(outcomes) == 5
    assert all(o.status == "saved" for o in outcomes)
    texts = embedder.embed.call_args[0][0]
    assert len(texts) == 5
    embedder.embed.assert_awaited_once()

    embedding_repo.bulk_upsert_embeddings.assert_awaited_once()
    records = embedding_repo.bulk_upsert_embeddings.call_args[0][0]
    assert len(records) == 5


async def test_embedding_failure_is_non_fatal(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    embedding_repo: AsyncMock,
    event_dispatcher: AsyncMock,
) -> None:
    places_service.create_batch.return_value = [_make_saved_object("place-1")]
    embedding_repo.bulk_upsert_embeddings = AsyncMock(
        side_effect=RuntimeError("DB error")
    )

    outcomes = await service.save_and_emit([_make_validated()], user_id="user-1")

    assert len(outcomes) == 1
    assert outcomes[0].status == "saved"
    event_dispatcher.dispatch.assert_awaited_once()


# ---------------------------------------------------------------------------
# Ordering invariant: DB writes → dispatch → embeddings
# ---------------------------------------------------------------------------


async def test_place_saved_dispatched_before_embeddings(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    event_dispatcher: AsyncMock,
    embedding_repo: AsyncMock,
) -> None:
    places_service.create_batch.return_value = [_make_saved_object("place-1")]
    call_order: list[str] = []

    async def dispatch_side_effect(event: object) -> None:
        call_order.append("dispatch")

    async def embed_side_effect(records: list) -> None:
        call_order.append("embed_bulk")

    event_dispatcher.dispatch = AsyncMock(side_effect=dispatch_side_effect)
    embedding_repo.bulk_upsert_embeddings = AsyncMock(side_effect=embed_side_effect)

    await service.save_and_emit([_make_validated()], user_id="user-1")

    assert call_order == ["dispatch", "embed_bulk"]


# ---------------------------------------------------------------------------
# Multi-place: one PlaceSaved with all saved IDs only
# ---------------------------------------------------------------------------


async def test_multiple_places_one_place_saved_event_with_all_ids(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    event_dispatcher: AsyncMock,
    embedder: AsyncMock,
) -> None:
    places_service.create_batch.return_value = [
        _make_saved_object("p-a", "Place A"),
        _make_saved_object("p-b", "Place B"),
    ]
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
    vcs = [
        _make_validated("Place A", external_id="ext_a"),
        _make_validated("Place B", external_id="ext_b"),
    ]

    outcomes = await service.save_and_emit(vcs, user_id="user-1")

    saved_ids = [o.place_id for o in outcomes if o.status == "saved"]
    event_dispatcher.dispatch.assert_awaited_once()
    event: PlaceSaved = event_dispatcher.dispatch.call_args[0][0]
    assert set(event.place_ids) == set(saved_ids)
    assert len(event.place_ids) == 2


async def test_mixed_saved_and_below_threshold_only_saved_in_event(
    service: ExtractionPersistenceService,
    places_service: AsyncMock,
    event_dispatcher: AsyncMock,
    embedder: AsyncMock,
) -> None:
    places_service.create_batch.return_value = [
        _make_saved_object("p-good", "Good Place")
    ]
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024])
    vcs = [
        _make_validated("Good Place", external_id="ext_good", confidence=0.85),
        _make_validated("Low Conf", external_id="ext_low", confidence=0.50),
    ]

    outcomes = await service.save_and_emit(vcs, user_id="user-1")

    saved = [o for o in outcomes if o.status == "saved"]
    below = [o for o in outcomes if o.status == "below_threshold"]
    assert len(saved) == 1
    assert len(below) == 1

    event_dispatcher.dispatch.assert_awaited_once()
    event: PlaceSaved = event_dispatcher.dispatch.call_args[0][0]
    assert len(event.place_ids) == 1
    assert event.place_ids[0] == saved[0].place_id
