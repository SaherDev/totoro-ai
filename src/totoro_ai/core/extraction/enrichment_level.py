"""EnrichmentLevel — one pass of (enrich → dedup → summarize)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from totoro_ai.core.extraction.dedup import dedup_candidates
from totoro_ai.core.extraction.protocols import Enricher
from totoro_ai.core.extraction.types import ExtractionContext

# (context, fired_enricher_names) -> human-readable summary
SummaryFn = Callable[[ExtractionContext, list[str]], str]


@dataclass
class EnrichmentLevel:
    """One level of the extraction cascade.

    A level bundles a list of enrichers with the bookkeeping that used
    to live inline in `ExtractionPipeline.run`: a name (used as the
    emit step suffix — `f"save.{name}"`), an optional URL requirement
    (so URL-only levels skip cleanly on text-only inputs), and a
    summary function that turns the post-enrichment state into a
    user-facing reasoning step.

    The pipeline runs levels in order; each level returns
    `(executed, summary)` so the pipeline knows whether to emit and
    whether to attempt validation after this pass.
    """

    name: str
    enrichers: list[Enricher]
    summary_fn: SummaryFn
    requires_url: bool = False
    fired: list[str] = field(default_factory=list, init=False, repr=False)

    async def run(self, context: ExtractionContext) -> tuple[bool, str]:
        if self.requires_url and context.url is None:
            return False, ""
        fired: list[str] = []
        for enricher in self.enrichers:
            await enricher.enrich(context)
            fired.append(type(enricher).__name__)
        dedup_candidates(context)
        return True, self.summary_fn(context, fired)
