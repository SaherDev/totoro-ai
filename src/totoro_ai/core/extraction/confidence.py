"""Extraction confidence scoring logic (ADR-029)."""

from totoro_ai.core.config import ConfidenceConfig
from totoro_ai.core.extraction.types import ExtractionLevel


def calculate_confidence(
    source: ExtractionLevel,
    match_modifier: float,
    corroborated: bool,
    config: ConfidenceConfig,
    signals: list[str] | None = None,
) -> float:
    """Compute confidence using multiplicative formula (ADR-029).

    Formula: min((base * match_modifier) + corroboration_bonus, config.max_score)

    Base score is determined by signals when present (LLM reports which evidence
    it used), otherwise falls back to base_scores[source.value].

    Signal priority (highest wins when multiple present):
        emoji_marker → 0.92  (explicit 📍 marker in caption)
        location_tag → 0.85  (platform-provided location confirmed it)
        caption      → 0.75  (venue named in caption text)
        hashtag      → 0.55  (hashtag was the primary clue)

    Multiple signals also trigger the corroboration bonus, since the LLM had
    independent evidence from more than one source.

    Args:
        source: ExtractionLevel that produced the candidate
        match_modifier: Google Places match quality as float (1.0=exact, 0.3=none)
        corroborated: True if two enrichers independently found the same name
        config: ConfidenceConfig loaded from app.yaml
        signals: Signal list from LLM (e.g. ["emoji_marker", "caption"])

    Returns:
        Confidence score in range [0.0, config.max_score]
    """
    if signals:
        base = max(config.signal_scores.get(s, 0.0) for s in signals)
        # Multiple independent signals = corroborated evidence
        if len(signals) >= 2:
            corroborated = True
    else:
        base = config.base_scores.get(source.value, 0.50)

    bonus = config.corroboration_bonus if corroborated else 0.0
    return min((base * match_modifier) + bonus, config.max_score)
