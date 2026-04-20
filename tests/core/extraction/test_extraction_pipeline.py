"""Tests for ExtractionPipeline (feature 019)."""

from unittest.mock import AsyncMock, MagicMock

from totoro_ai.core.extraction.types import (
    ExtractionLevel,
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
    inline_validator_returns=None,  # type: ignore[no-untyped-def]
    background_validator_returns=None,
    background_enrichers=None,
) -> tuple:
    """Returns (pipeline, enrichment_mock, validator_mock, bg_enrichers)."""
    from totoro_ai.core.config import (
        ConfidenceWeights,
        ExtractionConfig,
        ExtractionThresholds,
    )
    from totoro_ai.core.extraction.enrichment_pipeline import EnrichmentPipeline
    from totoro_ai.core.extraction.extraction_pipeline import ExtractionPipeline

    enrichment = MagicMock(spec=EnrichmentPipeline)
    enrichment.run = AsyncMock()

    # validator returns inline_validator_returns on first call,
    # background_validator_returns on second (Phase 3 re-validation)
    if background_validator_returns is not None:
        validator = MagicMock()
        validator.validate = AsyncMock(
            side_effect=[inline_validator_returns, background_validator_returns]
        )
    else:
        validator = MagicMock()
        validator.validate = AsyncMock(return_value=inline_validator_returns)

    if background_enrichers is None:
        background_enrichers = []

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
        background_enrichers=background_enrichers,
        extraction_config=extraction_config,
    )
    return pipeline, enrichment, validator, background_enrichers


async def test_inline_candidates_found_returns_results() -> None:
    results = [_make_validated()]
    pipeline, _, _, _ = _make_pipeline(inline_validator_returns=results)

    output = await pipeline.run(url="https://tiktok.com/1", user_id="u1")

    assert output == results


async def test_no_inline_candidates_no_bg_enrichers_returns_empty() -> None:
    pipeline, _, _, _ = _make_pipeline(inline_validator_returns=None)

    output = await pipeline.run(url="https://tiktok.com/1", user_id="u1")

    assert output == []


async def test_no_inline_candidates_bg_enrichers_run_inline() -> None:
    bg_enricher = MagicMock()
    bg_enricher.enrich = AsyncMock()
    bg_results = [_make_validated()]

    pipeline, _, _, _ = _make_pipeline(
        inline_validator_returns=None,
        background_validator_returns=bg_results,
        background_enrichers=[bg_enricher],
    )

    output = await pipeline.run(url="https://tiktok.com/1", user_id="u1")

    bg_enricher.enrich.assert_awaited_once()
    assert output == bg_results


async def test_bg_enrichers_find_nothing_returns_empty() -> None:
    bg_enricher = MagicMock()
    bg_enricher.enrich = AsyncMock()

    pipeline, _, _, _ = _make_pipeline(
        inline_validator_returns=None,
        background_validator_returns=None,
        background_enrichers=[bg_enricher],
    )

    output = await pipeline.run(url="https://tiktok.com/1", user_id="u1")

    assert output == []


async def test_plain_text_no_url_skips_bg_enrichers() -> None:
    bg_enricher = MagicMock()
    bg_enricher.enrich = AsyncMock()

    pipeline, _, _, _ = _make_pipeline(
        inline_validator_returns=None,
        background_enrichers=[bg_enricher],
    )

    output = await pipeline.run(url=None, user_id="u1", supplementary_text="Some place")

    bg_enricher.enrich.assert_not_called()
    assert output == []


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
    pipeline, _, _, _ = _make_pipeline(inline_validator_returns=[emoji, ner])

    output = await pipeline.run(
        url=None, user_id="u1", supplementary_text="RAMEN KAISUGI Bangkok"
    )

    assert isinstance(output, list)
    assert len(output) == 1
    assert output[0].resolved_by == ExtractionLevel.EMOJI_REGEX
    assert output[0].corroborated is True


async def test_plain_text_input_url_none_passes_through() -> None:
    results = [_make_validated()]
    pipeline, enrichment, _, _ = _make_pipeline(inline_validator_returns=results)

    output = await pipeline.run(
        url=None, user_id="u1", supplementary_text="Ramen House Paris"
    )

    assert output == results
    enrichment.run.assert_awaited_once()
    ctx = enrichment.run.call_args[0][0]
    assert ctx.url is None
    assert ctx.supplementary_text == "Ramen House Paris"


async def test_validator_receives_only_candidates() -> None:
    """validator.validate(candidates) — no user_id positional arg."""
    pipeline, _, validator, _ = _make_pipeline(inline_validator_returns=None)

    await pipeline.run(url="https://tiktok.com/1", user_id="u-xyz")

    assert validator.validate.await_count >= 1
    args = validator.validate.call_args.args
    kwargs = validator.validate.call_args.kwargs
    assert len(args) + len(kwargs) == 1
