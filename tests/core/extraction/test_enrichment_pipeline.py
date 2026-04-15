"""Tests for EnrichmentPipeline (Phase 6 — extraction cascade Run 2)."""

from unittest.mock import AsyncMock, MagicMock

from totoro_ai.core.extraction.enrichment_pipeline import EnrichmentPipeline
from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
)
from totoro_ai.core.places import PlaceCreate, PlaceType


def _candidate(
    name: str, source: ExtractionLevel, user_id: str = "u1"
) -> CandidatePlace:
    return CandidatePlace(
        place=PlaceCreate(
            user_id=user_id,
            place_name=name,
            place_type=PlaceType.food_and_drink,
        ),
        source=source,
    )


def _ctx() -> ExtractionContext:
    return ExtractionContext(url="https://example.com/video", user_id="u1")


def _mock_enricher(side_effect=None):  # type: ignore[no-untyped-def]
    """Return an Enricher-compatible mock (has .enrich async method)."""
    enricher = MagicMock()
    enricher.enrich = AsyncMock(side_effect=side_effect)
    return enricher


async def test_runs_all_enrichers_in_order() -> None:
    call_log: list[str] = []

    async def enrich_e1(context: ExtractionContext) -> None:
        call_log.append("e1")

    async def enrich_e2(context: ExtractionContext) -> None:
        call_log.append("e2")

    async def enrich_e3(context: ExtractionContext) -> None:
        call_log.append("e3")

    e1 = _mock_enricher(side_effect=enrich_e1)
    e2 = _mock_enricher(side_effect=enrich_e2)
    e3 = _mock_enricher(side_effect=enrich_e3)

    pipeline = EnrichmentPipeline(enrichers=[e1, e2, e3])
    ctx = _ctx()
    await pipeline.run(ctx)

    e1.enrich.assert_awaited_once_with(ctx)
    e2.enrich.assert_awaited_once_with(ctx)
    e3.enrich.assert_awaited_once_with(ctx)
    assert call_log == ["e1", "e2", "e3"]


async def test_dedup_called_after_all_enrichers() -> None:
    """Two enrichers append the same name → dedup collapses and marks corroborated."""

    async def add_candidate_1(context: ExtractionContext) -> None:
        context.candidates.append(
            _candidate("Ramen House", ExtractionLevel.EMOJI_REGEX)
        )

    async def add_candidate_2(context: ExtractionContext) -> None:
        context.candidates.append(_candidate("Ramen House", ExtractionLevel.LLM_NER))

    e1 = _mock_enricher(side_effect=add_candidate_1)
    e2 = _mock_enricher(side_effect=add_candidate_2)

    pipeline = EnrichmentPipeline(enrichers=[e1, e2])
    ctx = _ctx()
    await pipeline.run(ctx)

    # dedup should have run: 2 candidates collapsed to 1
    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].corroborated is True
    assert ctx.candidates[0].source == ExtractionLevel.EMOJI_REGEX


async def test_run_returns_none() -> None:
    e1 = _mock_enricher()
    pipeline = EnrichmentPipeline(enrichers=[e1])
    ctx = _ctx()
    result = await pipeline.run(ctx)
    assert result is None
