"""Tests for ExtractionPipeline (feature 019)."""

from unittest.mock import AsyncMock, MagicMock

from totoro_ai.core.extraction.types import (
    ExtractionLevel,
    ExtractionPending,
    ProvisionalResponse,
    ValidatedCandidate,
)
from totoro_ai.core.places import (
    PlaceAttributes,
    PlaceCreate,
    PlaceProvider,
    PlaceType,
)


def _make_validated(
    name: str = "Chez Claude",
    external_id: str = "place_abc",
    resolved_by: ExtractionLevel = ExtractionLevel.EMOJI_REGEX,
    confidence: float = 0.85,
) -> ValidatedCandidate:
    return ValidatedCandidate(
        place=PlaceCreate(
            user_id="u1",
            place_name=name,
            place_type=PlaceType.food_and_drink,
            attributes=PlaceAttributes(),
            provider=PlaceProvider.google,
            external_id=external_id,
        ),
        confidence=confidence,
        resolved_by=resolved_by,
        corroborated=False,
    )


def _make_pipeline(
    validator_returns=None,  # type: ignore[no-untyped-def]
    dispatcher=None,
) -> tuple:
    """Returns (pipeline, enrichment_mock, validator_mock, dispatcher_mock)."""
    from totoro_ai.core.config import (
        ConfidenceWeights,
        ExtractionConfig,
        ExtractionThresholds,
    )
    from totoro_ai.core.extraction.enrichment_pipeline import EnrichmentPipeline
    from totoro_ai.core.extraction.extraction_pipeline import ExtractionPipeline

    enrichment = MagicMock(spec=EnrichmentPipeline)
    enrichment.run = AsyncMock()

    validator = MagicMock()
    validator.validate = AsyncMock(return_value=validator_returns)

    if dispatcher is None:
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock()

    weights = ConfidenceWeights(
        base_scores={"CAPTION": 0.7},
        places_modifiers={"EXACT": 0.2},
    )
    extraction_config = ExtractionConfig(
        confidence_weights=weights,
        thresholds=ExtractionThresholds(),
    )

    pipeline = ExtractionPipeline(
        enrichment=enrichment,
        validator=validator,
        background_enrichers=[],
        event_dispatcher=dispatcher,
        extraction_config=extraction_config,
    )
    return pipeline, enrichment, validator, dispatcher


async def test_inline_candidates_found_returns_results() -> None:
    results = [_make_validated()]
    pipeline, enrichment, validator, dispatcher = _make_pipeline(
        validator_returns=results
    )

    output = await pipeline.run(url="https://tiktok.com/1", user_id="u1")

    assert output == results
    dispatcher.dispatch.assert_not_called()


async def test_no_inline_candidates_returns_provisional() -> None:
    pipeline, _, _, _ = _make_pipeline(validator_returns=None)

    output = await pipeline.run(url="https://tiktok.com/1", user_id="u1")

    assert isinstance(output, ProvisionalResponse)
    assert output.extraction_status == "processing"
    assert output.confidence == 0.0


async def test_no_inline_candidates_dispatches_extraction_pending() -> None:
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    pipeline, _, _, _ = _make_pipeline(validator_returns=None, dispatcher=dispatcher)

    await pipeline.run(url="https://tiktok.com/1", user_id="u42")

    dispatcher.dispatch.assert_awaited_once()
    event = dispatcher.dispatch.call_args[0][0]
    assert isinstance(event, ExtractionPending)
    assert event.event_type == "extraction_pending"


async def test_provisional_response_has_all_three_pending_levels() -> None:
    pipeline, _, _, _ = _make_pipeline(validator_returns=None)

    output = await pipeline.run(url="https://tiktok.com/1", user_id="u1")

    assert isinstance(output, ProvisionalResponse)
    assert ExtractionLevel.SUBTITLE_CHECK in output.pending_levels
    assert ExtractionLevel.WHISPER_AUDIO in output.pending_levels
    assert ExtractionLevel.VISION_FRAMES in output.pending_levels


async def test_extraction_pending_event_has_correct_user_id_and_url() -> None:
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    pipeline, _, _, _ = _make_pipeline(validator_returns=None, dispatcher=dispatcher)

    await pipeline.run(url="https://tiktok.com/video/99", user_id="user_xyz")

    event = dispatcher.dispatch.call_args[0][0]
    assert event.user_id == "user_xyz"
    assert event.url == "https://tiktok.com/video/99"


async def test_same_provider_id_deduped_after_validation() -> None:
    """Two validated candidates resolving to the same provider_id are
    collapsed into one with the corroboration bonus applied."""
    emoji = _make_validated(
        name="RAMEN KAISUGI Bangkok",
        external_id="ChIJrUYs1Xuf4jARDnd40CFUUAE",
        resolved_by=ExtractionLevel.EMOJI_REGEX,
        confidence=0.76,
    )
    ner = _make_validated(
        name="RAMEN KAISUGI",
        external_id="ChIJrUYs1Xuf4jARDnd40CFUUAE",
        resolved_by=ExtractionLevel.LLM_NER,
        confidence=0.64,
    )
    pipeline, _, _, _ = _make_pipeline(validator_returns=[emoji, ner])

    output = await pipeline.run(
        url=None, user_id="u1", supplementary_text="RAMEN KAISUGI Bangkok"
    )

    assert isinstance(output, list)
    assert len(output) == 1
    assert output[0].resolved_by == ExtractionLevel.EMOJI_REGEX
    assert output[0].corroborated is True


async def test_plain_text_input_url_none_passes_through() -> None:
    results = [_make_validated()]
    pipeline, enrichment, validator, dispatcher = _make_pipeline(
        validator_returns=results
    )

    output = await pipeline.run(
        url=None, user_id="u1", supplementary_text="Ramen House Paris"
    )

    assert output == results
    enrichment.run.assert_awaited_once()
    ctx = enrichment.run.call_args[0][0]
    assert ctx.url is None
    assert ctx.supplementary_text == "Ramen House Paris"


async def test_validator_receives_only_candidates() -> None:
    """validator.validate(candidates) — no user_id positional arg.

    The user_id is already stamped onto each CandidatePlace's inner
    PlaceCreate at enricher time, so the validator doesn't need it.
    """
    pipeline, _, validator, _ = _make_pipeline(validator_returns=None)

    await pipeline.run(url="https://tiktok.com/1", user_id="u-xyz")

    validator.validate.assert_awaited_once()
    args = validator.validate.call_args.args
    kwargs = validator.validate.call_args.kwargs
    assert len(args) + len(kwargs) == 1
