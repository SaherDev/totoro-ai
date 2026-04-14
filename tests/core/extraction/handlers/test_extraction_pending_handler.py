"""Tests for ExtractionPendingHandler (ADR-054 / feature 019)."""

from unittest.mock import AsyncMock, MagicMock

from totoro_ai.core.extraction.handlers.extraction_pending import (
    ExtractionPendingHandler,
)
from totoro_ai.core.extraction.persistence import (
    ExtractionPersistenceService,
    PlaceSaveOutcome,
)
from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository
from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
    ExtractionPending,
    ValidatedCandidate,
)
from totoro_ai.core.places import (
    PlaceAttributes,
    PlaceCreate,
    PlaceObject,
    PlaceProvider,
    PlaceType,
)


def _make_place_create(
    place_name: str = "Chez Claude",
    external_id: str = "place_99",
    provider: PlaceProvider | None = PlaceProvider.google,
) -> PlaceCreate:
    return PlaceCreate(
        user_id="u1",
        place_name=place_name,
        place_type=PlaceType.food_and_drink,
        subcategory="restaurant",
        attributes=PlaceAttributes(cuisine="french"),
        provider=provider,
        external_id=external_id,
    )


def _make_validated(name: str = "Chez Claude") -> ValidatedCandidate:
    return ValidatedCandidate(
        place=_make_place_create(place_name=name),
        confidence=0.72,
        resolved_by=ExtractionLevel.SUBTITLE_CHECK,
        corroborated=False,
    )


def _make_saved_object(
    place_id: str = "place-id-1",
    place_name: str = "Chez Claude",
) -> PlaceObject:
    return PlaceObject(
        place_id=place_id,
        place_name=place_name,
        place_type=PlaceType.food_and_drink,
        subcategory="restaurant",
        attributes=PlaceAttributes(cuisine="french"),
        provider_id="google:place_99",
    )


def _make_event(
    candidates: list[CandidatePlace] | None = None,
    request_id: str = "test-req-id",
) -> ExtractionPending:
    ctx = ExtractionContext(url="https://tiktok.com/1", user_id="u1")
    if candidates:
        ctx.candidates = candidates
    return ExtractionPending(
        user_id="u1",
        url="https://tiktok.com/1",
        pending_levels=[
            ExtractionLevel.SUBTITLE_CHECK,
            ExtractionLevel.WHISPER_AUDIO,
            ExtractionLevel.VISION_FRAMES,
        ],
        context=ctx,
        request_id=request_id,
    )


def _mock_enricher(side_effect=None):  # type: ignore[no-untyped-def]
    enricher = MagicMock()
    enricher.enrich = AsyncMock(side_effect=side_effect)
    return enricher


def _make_handler(
    enrichers: list | None = None,
    validator: MagicMock | None = None,
    persistence: AsyncMock | None = None,
    status_repo: AsyncMock | None = None,
) -> ExtractionPendingHandler:
    if validator is None:
        validator = MagicMock()
        validator.validate = AsyncMock(return_value=None)
    if persistence is None:
        persistence = AsyncMock(spec=ExtractionPersistenceService)
    if status_repo is None:
        status_repo = AsyncMock(spec=ExtractionStatusRepository)
    return ExtractionPendingHandler(
        background_enrichers=enrichers or [],
        validator=validator,
        persistence=persistence,
        status_repo=status_repo,
    )


def _append_candidate(name: str, source: ExtractionLevel):  # type: ignore[no-untyped-def]
    async def _inner(context: ExtractionContext) -> None:
        context.candidates.append(
            CandidatePlace(
                place=PlaceCreate(
                    user_id=context.user_id,
                    place_name=name,
                    place_type=PlaceType.food_and_drink,
                ),
                source=source,
            )
        )

    return _inner


# ---------------------------------------------------------------------------
# Enricher ordering
# ---------------------------------------------------------------------------


async def test_all_background_enrichers_called_in_order() -> None:
    call_log: list[str] = []

    async def e1(context: ExtractionContext) -> None:
        call_log.append("e1")

    async def e2(context: ExtractionContext) -> None:
        call_log.append("e2")

    async def e3(context: ExtractionContext) -> None:
        call_log.append("e3")

    enrichers = [_mock_enricher(e1), _mock_enricher(e2), _mock_enricher(e3)]
    handler = _make_handler(enrichers=enrichers)
    await handler.handle(_make_event())

    assert call_log == ["e1", "e2", "e3"]


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


async def test_dedup_called_after_enrichers() -> None:
    enrichers = [
        _mock_enricher(
            _append_candidate("Ramen House", ExtractionLevel.SUBTITLE_CHECK)
        ),
        _mock_enricher(
            _append_candidate("Ramen House", ExtractionLevel.WHISPER_AUDIO)
        ),
    ]
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=None)
    handler = _make_handler(enrichers=enrichers, validator=validator)
    event = _make_event()
    await handler.handle(event)

    assert len(event.context.candidates) == 1
    assert event.context.candidates[0].corroborated is True


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


async def test_validator_called_with_enriched_candidates() -> None:
    enricher = _mock_enricher(
        _append_candidate("Sushi Bar", ExtractionLevel.SUBTITLE_CHECK)
    )
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=None)
    handler = _make_handler(enrichers=[enricher], validator=validator)
    event = _make_event()
    await handler.handle(event)

    validator.validate.assert_awaited_once()
    (candidates_arg,) = validator.validate.call_args.args
    assert len(candidates_arg) == 1
    assert candidates_arg[0].place.place_name == "Sushi Bar"
    assert candidates_arg[0].place.user_id == "u1"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def test_persistence_not_called_when_validator_returns_none() -> None:
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=None)
    persistence = AsyncMock(spec=ExtractionPersistenceService)
    handler = _make_handler(validator=validator, persistence=persistence)
    await handler.handle(_make_event())

    persistence.save_and_emit.assert_not_called()


async def test_persistence_called_when_validator_returns_results() -> None:
    results = [_make_validated()]
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=results)
    persistence = AsyncMock(spec=ExtractionPersistenceService)
    handler = _make_handler(validator=validator, persistence=persistence)
    await handler.handle(_make_event())

    persistence.save_and_emit.assert_awaited_once_with(results, "u1")


# ---------------------------------------------------------------------------
# Status write — failed path
# ---------------------------------------------------------------------------


async def test_status_write_failed_when_validator_finds_nothing() -> None:
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=None)
    status_repo = AsyncMock(spec=ExtractionStatusRepository)
    handler = _make_handler(validator=validator, status_repo=status_repo)

    await handler.handle(_make_event(request_id="req-abc"))

    status_repo.write.assert_awaited_once()
    req_id, payload = status_repo.write.call_args.args
    assert req_id == "req-abc"
    assert payload["results"] == [
        {"place": None, "confidence": None, "status": "failed"}
    ]


async def test_status_write_failed_when_validator_returns_empty_list() -> None:
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=[])
    status_repo = AsyncMock(spec=ExtractionStatusRepository)
    handler = _make_handler(validator=validator, status_repo=status_repo)

    await handler.handle(_make_event(request_id="req-empty"))

    status_repo.write.assert_awaited_once()
    req_id, payload = status_repo.write.call_args.args
    assert req_id == "req-empty"
    assert payload["results"] == [
        {"place": None, "confidence": None, "status": "failed"}
    ]


# ---------------------------------------------------------------------------
# Status write — success path
# ---------------------------------------------------------------------------


async def test_status_payload_results_carry_full_place_object_and_confidence() -> None:
    """Each entry in `results` is `{place: PlaceObject, confidence, status}`."""
    validated = _make_validated("Ramen Hero")
    saved_place = _make_saved_object("place-id-1", "Ramen Hero")
    outcomes = [
        PlaceSaveOutcome(
            metadata=validated,
            place=saved_place,
            place_id="place-id-1",
            status="saved",
        )
    ]
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=[validated])
    persistence = AsyncMock(spec=ExtractionPersistenceService)
    persistence.save_and_emit = AsyncMock(return_value=outcomes)
    status_repo = AsyncMock(spec=ExtractionStatusRepository)
    handler = _make_handler(
        validator=validator, persistence=persistence, status_repo=status_repo
    )

    await handler.handle(_make_event(request_id="req-xyz"))

    status_repo.write.assert_awaited_once()
    req_id, payload = status_repo.write.call_args.args
    assert req_id == "req-xyz"
    assert len(payload["results"]) == 1
    item = payload["results"][0]
    assert item["status"] == "saved"
    assert item["confidence"] == validated.confidence
    place_entry = item["place"]
    assert place_entry is not None
    assert place_entry["place_id"] == "place-id-1"
    assert place_entry["place_name"] == "Ramen Hero"
    assert place_entry["place_type"] == PlaceType.food_and_drink.value
    assert place_entry["subcategory"] == "restaurant"
    assert place_entry["provider_id"] == "google:place_99"
    assert place_entry["attributes"]["cuisine"] == "french"


async def test_status_payload_below_threshold_collapses_to_failed_item() -> None:
    """Below-threshold outcomes surface with status='failed' and no place."""
    validated_ok = _make_validated("Good Place")
    validated_low = _make_validated("Low Conf Place")
    outcomes = [
        PlaceSaveOutcome(
            metadata=validated_ok,
            place=_make_saved_object("p1", "Good Place"),
            place_id="p1",
            status="saved",
        ),
        PlaceSaveOutcome(
            metadata=validated_low,
            place=None,
            place_id=None,
            status="below_threshold",
        ),
    ]
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=[validated_ok, validated_low])
    persistence = AsyncMock(spec=ExtractionPersistenceService)
    persistence.save_and_emit = AsyncMock(return_value=outcomes)
    status_repo = AsyncMock(spec=ExtractionStatusRepository)
    handler = _make_handler(
        validator=validator, persistence=persistence, status_repo=status_repo
    )

    await handler.handle(_make_event(request_id="req-mix"))

    payload = status_repo.write.call_args.args[1]
    assert len(payload["results"]) == 2
    assert payload["results"][0]["status"] == "saved"
    assert payload["results"][0]["place"]["place_id"] == "p1"
    assert payload["results"][1]["status"] == "failed"
    assert payload["results"][1]["place"] is None
    assert payload["results"][1]["confidence"] == validated_low.confidence


async def test_status_write_uses_request_id_from_event() -> None:
    validated = _make_validated()
    saved_place = _make_saved_object("p1")
    outcomes = [
        PlaceSaveOutcome(
            metadata=validated, place=saved_place, place_id="p1", status="saved"
        )
    ]
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=[validated])
    persistence = AsyncMock(spec=ExtractionPersistenceService)
    persistence.save_and_emit = AsyncMock(return_value=outcomes)
    status_repo = AsyncMock(spec=ExtractionStatusRepository)
    handler = _make_handler(
        validator=validator, persistence=persistence, status_repo=status_repo
    )

    await handler.handle(_make_event(request_id="unique-req-99"))

    written_req_id = status_repo.write.call_args[0][0]
    assert written_req_id == "unique-req-99"
