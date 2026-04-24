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

    Two phases run inside a level:

    1. **enrichers** — text/signal producers. Each one mutates context
       (sets caption/transcript/title, or appends candidates from
       sources like a vision model). They run sequentially; after they
       finish, `dedup_candidates` collapses near-duplicate candidates.
    2. **finalizer** (optional) — a "harvester" enricher that reads the
       text fields the producers just populated and emits candidates
       from them. In practice this is `LLMNEREnricher`, which performs
       one consolidated NER call over caption + transcript +
       supplementary_text. A second dedup runs after the finalizer.

    A level skips entirely when `requires_url=True` and `context.url`
    is `None`. The pipeline calls `level.run(context)` and uses the
    returned `(executed, summary)` to decide whether to emit a step
    and run validation.
    """

    name: str
    enrichers: list[Enricher]
    summary_fn: SummaryFn
    requires_url: bool = False
    finalizer: Enricher | None = None
    fired: list[str] = field(default_factory=list, init=False, repr=False)

    async def run(self, context: ExtractionContext) -> tuple[bool, str]:
        if self.requires_url and context.url is None:
            return False, ""
        fired: list[str] = []
        for enricher in self.enrichers:
            await enricher.enrich(context)
            fired.append(type(enricher).__name__)
        dedup_candidates(context)
        if self.finalizer is not None:
            await self.finalizer.enrich(context)
            fired.append(type(self.finalizer).__name__)
            dedup_candidates(context)
        return True, self.summary_fn(context, fired)
