"""Tests for ExtractionPendingHandler: enrichment, dedup, persistence, status writes."""

from unittest.mock import AsyncMock, MagicMock

from totoro_ai.core.extraction.handlers.extraction_pending import (
    ExtractionPendingHandler,
)
from totoro_ai.core.extraction.persistence import ExtractionPersistenceService
from totoro_ai.core.extraction.status_repository import ExtractionStatusRepository
from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
    ExtractionPending,
    ExtractionResult,
)


def _make_result(name: str = "Chez Claude") -> ExtractionResult:
    return ExtractionResult(
        place_name=name,
        address=None,
        city=None,
        cuisine=None,
        confidence=0.72,
        resolved_by=ExtractionLevel.SUBTITLE_CHECK,
        corroborated=False,
        external_provider="google",
        external_id="place_99",
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
    """Two enrichers add same-name candidates → dedup marks winner corroborated."""

    async def add_e1(context: ExtractionContext) -> None:
        context.candidates.append(
            CandidatePlace(
                name="Ramen House", city=None, cuisine=None,
                source=ExtractionLevel.SUBTITLE_CHECK,
            )
        )

    async def add_e2(context: ExtractionContext) -> None:
        context.candidates.append(
            CandidatePlace(
                name="Ramen House", city=None, cuisine=None,
                source=ExtractionLevel.WHISPER_AUDIO,
            )
        )

    enrichers = [_mock_enricher(add_e1), _mock_enricher(add_e2)]
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
    async def add_candidate(context: ExtractionContext) -> None:
        context.candidates.append(
            CandidatePlace(
                name="Sushi Bar", city=None, cuisine=None,
                source=ExtractionLevel.SUBTITLE_CHECK,
            )
        )

    enricher = _mock_enricher(add_candidate)
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=None)
    handler = _make_handler(enrichers=[enricher], validator=validator)
    event = _make_event()
    await handler.handle(event)

    validator.validate.assert_awaited_once()
    candidates_arg = validator.validate.call_args[0][0]
    assert len(candidates_arg) == 1
    assert candidates_arg[0].name == "Sushi Bar"


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
    results = [_make_result()]
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=results)
    persistence = AsyncMock(spec=ExtractionPersistenceService)
    handler = _make_handler(validator=validator, persistence=persistence)
    await handler.handle(_make_event())

    persistence.save_and_emit.assert_awaited_once_with(results, "u1")


# ---------------------------------------------------------------------------
# Status write — no results (failed path)
# ---------------------------------------------------------------------------


async def test_status_write_failed_when_validator_finds_nothing() -> None:
    """Handler writes {"extraction_status": "failed"} when validator returns nothing."""
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=None)
    status_repo = AsyncMock(spec=ExtractionStatusRepository)
    handler = _make_handler(validator=validator, status_repo=status_repo)

    await handler.handle(_make_event(request_id="req-abc"))

    status_repo.write.assert_awaited_once_with(
        "req-abc", {"extraction_status": "failed"}
    )


async def test_status_write_failed_when_validator_returns_empty_list() -> None:
    """Handler writes failed status when validator returns empty list."""
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=[])
    status_repo = AsyncMock(spec=ExtractionStatusRepository)
    handler = _make_handler(validator=validator, status_repo=status_repo)

    await handler.handle(_make_event(request_id="req-empty"))

    status_repo.write.assert_awaited_once_with(
        "req-empty", {"extraction_status": "failed"}
    )


# ---------------------------------------------------------------------------
# Status write — success path
# ---------------------------------------------------------------------------


async def test_status_write_called_with_full_payload_on_success() -> None:
    """Handler writes full ExtractPlaceResponse-compatible dict on success."""
    results = [_make_result("Ramen Hero")]
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=results)
    persistence = AsyncMock(spec=ExtractionPersistenceService)
    persistence.save_and_emit = AsyncMock(return_value=["place-id-1"])
    status_repo = AsyncMock(spec=ExtractionStatusRepository)
    handler = _make_handler(
        validator=validator, persistence=persistence, status_repo=status_repo
    )

    await handler.handle(_make_event(request_id="req-xyz"))

    status_repo.write.assert_awaited_once()
    call_args = status_repo.write.call_args
    req_id, payload = call_args[0]
    assert req_id == "req-xyz"
    assert payload["extraction_status"] == "saved"
    assert payload["provisional"] is False
    assert len(payload["places"]) == 1
    assert payload["places"][0]["place_name"] == "Ramen Hero"
    assert payload["places"][0]["place_id"] == "place-id-1"


async def test_status_write_uses_request_id_from_event() -> None:
    """Handler forwards event.request_id to status_repo.write."""
    results = [_make_result()]
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=results)
    persistence = AsyncMock(spec=ExtractionPersistenceService)
    persistence.save_and_emit = AsyncMock(return_value=["p1"])
    status_repo = AsyncMock(spec=ExtractionStatusRepository)
    handler = _make_handler(
        validator=validator, persistence=persistence, status_repo=status_repo
    )

    await handler.handle(_make_event(request_id="unique-req-99"))

    written_req_id = status_repo.write.call_args[0][0]
    assert written_req_id == "unique-req-99"
