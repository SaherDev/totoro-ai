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

    A level is a list of pure text/signal-producing enrichers. They
    mutate context (set caption/transcript/title, or append candidates
    from sources like a vision model), then `dedup_candidates`
    collapses near-duplicate candidates. The pipeline owns the NER
    "harvest" step that runs after every executed level.

    A level skips entirely when `requires_url=True` and `context.url`
    is `None`. The pipeline calls `level.run(context)` and uses the
    returned `(executed, summary)` to decide whether to run NER,
    emit a step, and validate.
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
