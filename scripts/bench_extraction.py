"""Benchmark the extraction pipeline end-to-end.

Measures per-stage wall time and OpenAI token cost across a fixture set of
real inputs. Bypasses the DB layer (no PlaceRepository, no saves) so the
numbers reflect extraction work only.

Run from repo root:
    poetry run python scripts/bench_extraction.py

Reports:
    - per-input timing + status
    - aggregate latency (mean/p50/p95/max) for each phase
    - total OpenAI token usage + cost estimate
    - % of inputs resolved at each tier
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Make `src/` importable without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from totoro_ai.core.extraction.circuit_breaker import (  # noqa: E402
    CircuitBreakerEnricher,
    ParallelEnricherGroup,
)
from totoro_ai.core.extraction.enrichers.llm_ner import LLMNEREnricher  # noqa: E402
from totoro_ai.core.extraction.enrichers.subtitle_check import (  # noqa: E402
    SubtitleCheckEnricher,
)
from totoro_ai.core.extraction.enrichers.tiktok_oembed import (  # noqa: E402
    TikTokOEmbedEnricher,
)
from totoro_ai.core.extraction.enrichers.vision_frames import (  # noqa: E402
    VisionFramesEnricher,
)
from totoro_ai.core.extraction.enrichers.whisper_audio import (  # noqa: E402
    WhisperAudioEnricher,
)
from totoro_ai.core.extraction.enrichers.ytdlp_metadata import (  # noqa: E402
    YtDlpMetadataEnricher,
)
from totoro_ai.core.extraction.enrichment_pipeline import (  # noqa: E402
    EnrichmentPipeline,
)
from totoro_ai.core.extraction.input_parser import parse_input  # noqa: E402
from totoro_ai.core.extraction.types import ExtractionContext  # noqa: E402
from totoro_ai.core.extraction.validator import GooglePlacesValidator  # noqa: E402
from totoro_ai.core.places import GooglePlacesClient  # noqa: E402
from totoro_ai.core.config import get_config, get_secrets  # noqa: E402
from totoro_ai.providers.groq_client import GroqWhisperClient  # noqa: E402
from totoro_ai.providers.llm import (  # noqa: E402
    get_instructor_client,
    get_vision_extractor,
)


# ---- Pricing (USD per 1M tokens) -------------------------------------------
# https://openai.com/api/pricing/  (as of 2026)
PRICING = {
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "gpt-4o": {"in": 2.50, "out": 10.00},
}
GOOGLE_PLACES_COST_PER_CALL = 0.017  # $17 per 1000 requests (Text Search)


# ---- Token tracker ----------------------------------------------------------
@dataclass
class TokenUsage:
    model: str
    prompt_tokens: int
    completion_tokens: int


token_log: list[TokenUsage] = []


def patch_openai_for_token_tracking() -> None:
    """Monkey-patch AsyncOpenAI chat.completions.create to capture usage."""
    from openai.resources.chat.completions import AsyncCompletions

    original = AsyncCompletions.create

    async def wrapped(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        response = await original(self, *args, **kwargs)
        usage = getattr(response, "usage", None)
        if usage is not None:
            token_log.append(
                TokenUsage(
                    model=getattr(response, "model", kwargs.get("model", "?")),
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                )
            )
        return response

    AsyncCompletions.create = wrapped  # type: ignore[method-assign]


# ---- Timing wrapper ---------------------------------------------------------
@dataclass
class StageTiming:
    name: str
    seconds: float
    candidates_added: int


class TimedEnricher:
    """Wraps an enricher, records wall time + candidate delta per call."""

    def __init__(self, inner: Any, name: str, recorder: list[StageTiming]) -> None:
        self._inner = inner
        self._name = name
        self._recorder = recorder

    async def enrich(self, context: ExtractionContext) -> None:
        before = len(context.candidates)
        t0 = time.perf_counter()
        try:
            await self._inner.enrich(context)
        finally:
            dt = time.perf_counter() - t0
            self._recorder.append(
                StageTiming(
                    name=self._name,
                    seconds=dt,
                    candidates_added=len(context.candidates) - before,
                )
            )


class TimedValidator:
    def __init__(self, inner: Any, recorder: list[StageTiming]) -> None:
        self._inner = inner
        self._recorder = recorder
        self.calls = 0

    async def validate(self, candidates: list[Any]) -> list[Any]:
        self.calls += 1
        t0 = time.perf_counter()
        try:
            return await self._inner.validate(candidates)
        finally:
            dt = time.perf_counter() - t0
            self._recorder.append(
                StageTiming(
                    name="google_places_validate",
                    seconds=dt,
                    candidates_added=0,
                )
            )


# ---- Pipeline construction (no DB) ------------------------------------------
def build_inline_enrichers(recorder: list[StageTiming]) -> EnrichmentPipeline:
    instructor = get_instructor_client("intent_parser")
    tiktok = TimedEnricher(
        CircuitBreakerEnricher(TikTokOEmbedEnricher()),
        "tiktok_oembed",
        recorder,
    )
    ytdlp = TimedEnricher(
        CircuitBreakerEnricher(YtDlpMetadataEnricher()),
        "ytdlp_metadata",
        recorder,
    )
    llm_ner = TimedEnricher(
        LLMNEREnricher(instructor_client=instructor),
        "llm_ner",
        recorder,
    )
    return EnrichmentPipeline(
        [ParallelEnricherGroup([tiktok, ytdlp]), llm_ner]  # type: ignore[list-item]
    )


def build_background_enrichers(recorder: list[StageTiming]) -> list[Any]:
    instructor = get_instructor_client("intent_parser")
    return [
        TimedEnricher(
            SubtitleCheckEnricher(instructor_client=instructor),
            "subtitle_check",
            recorder,
        ),
        TimedEnricher(
            WhisperAudioEnricher(
                groq_client=GroqWhisperClient(
                    api_key=get_secrets().GROQ_API_KEY or ""
                ),
                instructor_client=instructor,
            ),
            "whisper_audio",
            recorder,
        ),
        TimedEnricher(
            VisionFramesEnricher(vision_extractor=get_vision_extractor()),
            "vision_frames",
            recorder,
        ),
    ]


# ---- Fixtures ---------------------------------------------------------------
FIXTURES: list[tuple[str, str]] = [
    # (raw_input, category)
    ("cheap ramen near Sukhumvit", "text"),
    ("best Thai boat noodles in Bangkok", "text"),
    ("Nara Eatery Bangkok", "text"),
    ("Nihonryori RyuGin Tokyo", "text"),
    ("Jay Fai Michelin street food Bangkok", "text"),
    ("I had amazing sushi at Sukiyabashi Jiro last week", "text"),
    ("https://www.tiktok.com/@markwiens/video/7229876543210987654", "tiktok"),
    ("https://www.tiktok.com/@foodie.bkk/video/7198765432109876543", "tiktok"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
    ("https://www.youtube.com/watch?v=1La4QzGeaaQ", "youtube"),
]


# ---- Main ------------------------------------------------------------------
@dataclass
class RunResult:
    raw_input: str
    category: str
    status: str  # "resolved_inline", "resolved_background", "no_match", "error"
    stages: list[StageTiming] = field(default_factory=list)
    total_seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    openai_cost_usd: float = 0.0
    places_cost_usd: float = 0.0
    candidates: int = 0
    error: str | None = None


def _token_cost(log: list[TokenUsage]) -> tuple[int, int, float]:
    ti = to = 0
    cost = 0.0
    for entry in log:
        # Strip version suffix e.g. gpt-4o-mini-2024-07-18 → gpt-4o-mini
        key = next((k for k in PRICING if entry.model.startswith(k)), None)
        ti += entry.prompt_tokens
        to += entry.completion_tokens
        if key:
            cost += (
                entry.prompt_tokens * PRICING[key]["in"] / 1_000_000
                + entry.completion_tokens * PRICING[key]["out"] / 1_000_000
            )
    return ti, to, cost


async def run_one(raw_input: str, category: str) -> RunResult:
    stages: list[StageTiming] = []
    token_log.clear()

    parsed = parse_input(raw_input)
    context = ExtractionContext(
        url=parsed.url,
        user_id="bench-user",
        supplementary_text=parsed.supplementary_text,
    )

    inline = build_inline_enrichers(stages)
    validator = TimedValidator(
        GooglePlacesValidator(
            places_client=GooglePlacesClient(),
            confidence_config=get_config().extraction.confidence,
        ),
        stages,
    )

    result = RunResult(raw_input=raw_input, category=category, status="no_match")

    t_total = time.perf_counter()
    try:
        # Phase 1: inline
        await inline.run(context)

        # Phase 2: validate
        validated = await validator.validate(context.candidates)

        if validated:
            result.status = "resolved_inline"
            result.candidates = len(validated)
        elif parsed.url is not None:
            # Phase 3: background (run sequentially so we can measure each)
            bg = build_background_enrichers(stages)
            for enricher in bg:
                await enricher.enrich(context)
                # Short-circuit: once we have candidates, try to validate
                if context.candidates:
                    bg_validated = await validator.validate(context.candidates)
                    if bg_validated:
                        result.status = "resolved_background"
                        result.candidates = len(bg_validated)
                        break
    except Exception as exc:  # noqa: BLE001
        result.status = "error"
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.total_seconds = time.perf_counter() - t_total
        result.stages = stages
        ti, to, cost = _token_cost(token_log)
        result.tokens_in = ti
        result.tokens_out = to
        result.openai_cost_usd = cost
        result.places_cost_usd = validator.calls * GOOGLE_PLACES_COST_PER_CALL
    return result


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100)[int(p) - 1]


def report(results: list[RunResult]) -> None:
    print("\n" + "=" * 78)
    print("PER-INPUT RESULTS")
    print("=" * 78)
    for r in results:
        tag = r.status
        print(
            f"[{tag:20s}] {r.total_seconds:6.2f}s  "
            f"in={r.tokens_in:5d} out={r.tokens_out:4d}  "
            f"${r.openai_cost_usd + r.places_cost_usd:.4f}  "
            f"candidates={r.candidates}  "
            f"{r.raw_input[:50]}"
        )
        if r.error:
            print(f"    ERROR: {r.error}")
        for s in r.stages:
            print(f"    {s.name:25s} {s.seconds * 1000:7.1f}ms  +{s.candidates_added}")

    print("\n" + "=" * 78)
    print("AGGREGATE")
    print("=" * 78)
    total = len(results)
    inline = sum(1 for r in results if r.status == "resolved_inline")
    background = sum(1 for r in results if r.status == "resolved_background")
    no_match = sum(1 for r in results if r.status == "no_match")
    errors = sum(1 for r in results if r.status == "error")
    print(f"Total inputs:         {total}")
    print(f"Resolved inline:      {inline} ({100 * inline / total:.0f}%)")
    print(f"Resolved background:  {background} ({100 * background / total:.0f}%)")
    print(f"No match:             {no_match}")
    print(f"Errors:               {errors}")

    durations = [r.total_seconds for r in results if r.status != "error"]
    if durations:
        print("\nLatency (end-to-end, seconds):")
        print(f"  mean: {statistics.mean(durations):.2f}")
        print(f"  p50:  {statistics.median(durations):.2f}")
        print(f"  p95:  {pct(durations, 95):.2f}")
        print(f"  max:  {max(durations):.2f}")

    inline_durations = [
        r.total_seconds for r in results if r.status == "resolved_inline"
    ]
    if inline_durations:
        under_2_5 = sum(1 for d in inline_durations if d < 2.5)
        print("\nInline-only latency (seconds):")
        print(f"  mean: {statistics.mean(inline_durations):.2f}")
        print(f"  p50:  {statistics.median(inline_durations):.2f}")
        print(f"  max:  {max(inline_durations):.2f}")
        print(
            f"  <2.5s: {under_2_5}/{len(inline_durations)} "
            f"({100 * under_2_5 / len(inline_durations):.0f}%)"
        )

    total_openai = sum(r.openai_cost_usd for r in results)
    total_places = sum(r.places_cost_usd for r in results)
    total_cost = total_openai + total_places
    print("\nCost:")
    print(f"  OpenAI:       ${total_openai:.4f}")
    print(f"  Google Places: ${total_places:.4f}")
    print(f"  Total:        ${total_cost:.4f}")
    print(f"  Per request:  ${total_cost / total:.4f}")

    print("\nPer-stage timing (mean ms across all calls):")
    stage_times: dict[str, list[float]] = {}
    for r in results:
        for s in r.stages:
            stage_times.setdefault(s.name, []).append(s.seconds * 1000)
    for name, ts in sorted(stage_times.items(), key=lambda x: -statistics.mean(x[1])):
        print(
            f"  {name:25s} mean={statistics.mean(ts):7.1f}ms  "
            f"max={max(ts):7.1f}ms  n={len(ts)}"
        )


async def main() -> None:
    patch_openai_for_token_tracking()
    results: list[RunResult] = []
    for raw_input, category in FIXTURES:
        print(f"Running: {raw_input[:60]} ...")
        result = await run_one(raw_input, category)
        results.append(result)
    report(results)

    out_path = Path(__file__).parent / "bench_extraction_results.json"
    out_path.write_text(
        json.dumps(
            [
                {
                    "raw_input": r.raw_input,
                    "category": r.category,
                    "status": r.status,
                    "total_seconds": r.total_seconds,
                    "tokens_in": r.tokens_in,
                    "tokens_out": r.tokens_out,
                    "openai_cost_usd": r.openai_cost_usd,
                    "places_cost_usd": r.places_cost_usd,
                    "candidates": r.candidates,
                    "error": r.error,
                    "stages": [
                        {
                            "name": s.name,
                            "seconds": s.seconds,
                            "candidates_added": s.candidates_added,
                        }
                        for s in r.stages
                    ],
                }
                for r in results
            ],
            indent=2,
        )
    )
    print(f"\nRaw results written to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
