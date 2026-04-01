"""Candidate deduplication for the extraction pipeline.

Merges same-name candidates from different sources at the end of the
enrichment phase. When two sources independently find the same name,
the merged candidate gets corroborated=True for a confidence bonus.
"""

from totoro_ai.core.extraction.models import CandidatePlace, ExtractionContext


def dedup_candidates(context: ExtractionContext) -> None:
    """Deduplicate candidates in-place on the context.

    Groups candidates by normalized name. When multiple sources found the
    same name, keeps the one from the highest-priority source (lowest enum
    index) and marks it as corroborated.
    """
    if len(context.candidates) <= 1:
        return

    seen: dict[str, list[CandidatePlace]] = {}
    for candidate in context.candidates:
        key = candidate.name.strip().lower()
        seen.setdefault(key, []).append(candidate)

    deduped: list[CandidatePlace] = []
    for group in seen.values():
        if len(group) == 1:
            deduped.append(group[0])
        else:
            # Multiple sources found same name — keep richest data, mark corroborated
            best = _pick_best(group)
            best.corroborated = True
            # Fill missing fields from other candidates
            for other in group:
                if other is best:
                    continue
                if not best.city and other.city:
                    best.city = other.city
                if not best.cuisine and other.cuisine:
                    best.cuisine = other.cuisine
            deduped.append(best)

    context.candidates = deduped


def _pick_best(group: list[CandidatePlace]) -> CandidatePlace:
    """Pick candidate from highest-priority source (lowest enum ordinal)."""
    from totoro_ai.core.extraction.models import ExtractionLevel

    level_order = list(ExtractionLevel)
    return min(group, key=lambda c: level_order.index(c.source))
