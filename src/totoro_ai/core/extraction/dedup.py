"""Candidate deduplication — collapses same-name candidates, marks corroborated."""

from __future__ import annotations

from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
)

_LEVEL_ORDER = list(ExtractionLevel)


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
        key = candidate.name.strip().lower()
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
