"""Confidence scoring logic for the extraction pipeline (ADR-029)."""

from totoro_ai.core.config import ConfidenceWeights
from totoro_ai.core.extraction.models import ExtractionLevel
from totoro_ai.core.extraction.places_client import PlacesMatchQuality


def compute_confidence(
    source: ExtractionLevel,
    match_quality: PlacesMatchQuality,
    weights: ConfidenceWeights,
    corroborated: bool = False,
) -> float:
    """Compute confidence score from extraction level and Places match quality.

    Formula: (base_score x match_modifier) + corroboration_bonus, capped at max_score.

    Args:
        source: Which extraction level produced the candidate
        match_quality: Google Places match quality (EXACT, FUZZY, CATEGORY_ONLY, NONE)
        weights: Confidence weight config loaded from app.yaml (ADR-029)
        corroborated: Whether two independent sources found the same name

    Returns:
        Confidence score between 0.0 and max_score
    """
    none_cap = weights.places_modifiers.get("NONE_CAP", 0.30)

    # Step 1: Base score from extraction level
    base = weights.base_scores.get(source.value, 0.60)

    # Step 2: Apply Places match quality modifier
    if match_quality == PlacesMatchQuality.EXACT:
        modifier = weights.places_modifiers.get("EXACT", 0.20)
    elif match_quality == PlacesMatchQuality.FUZZY:
        modifier = weights.places_modifiers.get("FUZZY", 0.15)
    elif match_quality == PlacesMatchQuality.CATEGORY_ONLY:
        modifier = weights.places_modifiers.get("CATEGORY_ONLY", 0.10)
    else:  # NONE
        return min(min(base, none_cap), weights.max_score)

    score = base + modifier

    # Step 3: Corroboration bonus
    if corroborated:
        score += weights.multi_source_bonus

    # Step 4: Apply max cap
    return min(score, weights.max_score)
