"""Candidate deduplication — collapses same-name candidates, marks corroborated."""

from __future__ import annotations

import re

from totoro_ai.core.config import ConfidenceConfig
from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
    ExtractionResult,
)

_LEVEL_ORDER = list(ExtractionLevel)


def _normalize(name: str) -> str:
    """Normalize a place name for dedup comparison.

    Lowercases, strips punctuation, and collapses whitespace so that
    "RAMEN KAISUGI", "Ramen Kaisugi!", and "ramen kaisugi" all map to the
    same key.
    """
    without_punct = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE)
    return " ".join(without_punct.lower().split())


def dedup_candidates(context: ExtractionContext) -> None:
    """Deduplicate context.candidates in-place.

    Groups by normalised name.  When multiple candidates share a name the one
    with the lowest ExtractionLevel index (highest priority) wins; it is
    marked corroborated=True.  Insertion order of first-occurrence is preserved.
    """
    if len(context.candidates) <= 1:
        return

    # Preserve insertion order; key = normalised name
    groups: dict[str, list[CandidatePlace]] = {}
    for candidate in context.candidates:
        key = _normalize(candidate.name)
        groups.setdefault(key, []).append(candidate)

    winners: list[CandidatePlace] = []
    for group in groups.values():
        if len(group) == 1:
            winners.append(group[0])
        else:
            winner = min(group, key=lambda c: _LEVEL_ORDER.index(c.source))
            winner.corroborated = True
            winners.append(winner)

    context.candidates = winners


def dedup_results_by_external_id(
    results: list[ExtractionResult],
    confidence_config: ConfidenceConfig,
) -> list[ExtractionResult]:
    """Post-validation dedup: collapse results that resolved to the same external_id.

    The pre-validation name dedup cannot catch cases where two enrichers
    produce slightly different name strings (e.g. "RAMEN KAISUGI Bangkok" vs
    "RAMEN KAISUGI") that Google Places resolves to the same place_id.

    When two results share the same external_id:
    - Keep the one with the highest-priority resolved_by source
      (same ordering as _LEVEL_ORDER).
    - Apply corroboration_bonus to the winner's confidence, capped at max_score.
    - Drop the other result entirely.

    Results with external_id=None pass through unchanged.
    """
    if len(results) <= 1:
        return results

    no_id: list[ExtractionResult] = []
    by_external_id: dict[str, list[ExtractionResult]] = {}

    for result in results:
        if result.external_id is None:
            no_id.append(result)
        else:
            by_external_id.setdefault(result.external_id, []).append(result)

    winners: list[ExtractionResult] = []
    for group in by_external_id.values():
        if len(group) == 1:
            winners.append(group[0])
        else:
            winner = min(group, key=lambda r: _LEVEL_ORDER.index(r.resolved_by))
            winner.confidence = min(
                winner.confidence + confidence_config.corroboration_bonus,
                confidence_config.max_score,
            )
            winner.corroborated = True
            # Inherit city from a lower-priority result if the winner has none.
            if winner.city is None:
                for r in group:
                    if r.city is not None:
                        winner.city = r.city
                        break
            winners.append(winner)

    return no_id + winners
