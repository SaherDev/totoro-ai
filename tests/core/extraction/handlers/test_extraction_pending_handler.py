"""Tests for ExtractionPendingHandler (Phase 7 — extraction cascade Run 2)."""

from unittest.mock import AsyncMock, MagicMock

from totoro_ai.core.extraction.handlers.extraction_pending import (
    ExtractionPendingHandler,
)
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


def _make_event(candidates: list[CandidatePlace] | None = None) -> ExtractionPending:
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
    )


def _mock_enricher(side_effect=None):  # type: ignore[no-untyped-def]
    enricher = MagicMock()
    enricher.enrich = AsyncMock(side_effect=side_effect)
    return enricher


async def test_all_background_enrichers_called_in_order() -> None:
    call_log: list[str] = []

    async def e1(context: ExtractionContext) -> None:
        call_log.append("e1")

    async def e2(context: ExtractionContext) -> None:
        call_log.append("e2")

    async def e3(context: ExtractionContext) -> None:
        call_log.append("e3")

    enrichers = [_mock_enricher(e1), _mock_enricher(e2), _mock_enricher(e3)]
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=None)
    persistence = MagicMock()

    handler = ExtractionPendingHandler(
        background_enrichers=enrichers,
        validator=validator,
        persistence=persistence,
    )
    await handler.handle(_make_event())

    assert call_log == ["e1", "e2", "e3"]


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
    persistence = MagicMock()

    handler = ExtractionPendingHandler(
        background_enrichers=enrichers,
        validator=validator,
        persistence=persistence,
    )
    event = _make_event()
    await handler.handle(event)

    # dedup ran: candidates collapsed to 1, winner corroborated
    assert len(event.context.candidates) == 1
    assert event.context.candidates[0].corroborated is True


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
    persistence = MagicMock()

    handler = ExtractionPendingHandler(
        background_enrichers=[enricher],
        validator=validator,
        persistence=persistence,
    )
    event = _make_event()
    await handler.handle(event)

    validator.validate.assert_awaited_once()
    candidates_arg = validator.validate.call_args[0][0]
    assert len(candidates_arg) == 1
    assert candidates_arg[0].name == "Sushi Bar"


async def test_persistence_not_called_when_validator_returns_none() -> None:
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=None)
    persistence = AsyncMock()

    handler = ExtractionPendingHandler(
        background_enrichers=[],
        validator=validator,
        persistence=persistence,
    )
    await handler.handle(_make_event())

    persistence.save_and_emit.assert_not_called()


async def test_persistence_called_when_validator_returns_results() -> None:
    results = [_make_result()]
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=results)
    persistence = AsyncMock()

    handler = ExtractionPendingHandler(
        background_enrichers=[],
        validator=validator,
        persistence=persistence,
    )
    await handler.handle(_make_event())

    persistence.save_and_emit.assert_awaited_once_with(results, "u1")
