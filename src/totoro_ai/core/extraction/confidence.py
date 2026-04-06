"""Extraction confidence scoring logic (ADR-029)."""

from totoro_ai.core.config import ConfidenceConfig
from totoro_ai.core.extraction.types import ExtractionLevel


def calculate_confidence(
    source: ExtractionLevel,
    match_modifier: float,
    corroborated: bool,
    config: ConfidenceConfig,
) -> float:
    """Compute confidence using multiplicative formula (ADR-029).

    Formula: min((base_score * match_modifier) + corroboration_bonus, config.max_score)

    max_score is configurable (default 0.97). No extraction path earns 1.0 — even
    perfect emoji regex + exact Google match involves two fallible steps.

    Args:
        source: ExtractionLevel that produced the candidate
        match_modifier: Google Places match quality as float (1.0=exact, 0.3=none)
        corroborated: True if two enrichers independently found the same name
        config: ConfidenceConfig loaded from app.yaml

    Returns:
        Confidence score in range [0.0, config.max_score]
    """
    base = config.base_scores.get(source.value, 0.50)
    bonus = config.corroboration_bonus if corroborated else 0.0
    return min((base * match_modifier) + bonus, config.max_score)
