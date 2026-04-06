"""Extraction source classification and confidence scoring logic."""

from enum import Enum

from totoro_ai.core.config import ConfidenceConfig, ConfidenceWeights
from totoro_ai.core.extraction.places_client import PlacesMatchQuality
from totoro_ai.core.extraction.types import ExtractionLevel


class ExtractionSource(str, Enum):
    """Source of extraction — determines base confidence score."""

    CAPTION = "CAPTION"  # TikTok oEmbed caption (current)
    PLAIN_TEXT = "PLAIN_TEXT"  # Plain text input (current)
    SPEECH = "SPEECH"  # Whisper transcription (will be supported later)
    OCR = "OCR"  # Frame OCR (will be supported later)


def compute_confidence(
    source: ExtractionSource,
    match_quality: PlacesMatchQuality,
    weights: ConfidenceWeights,
    corroborated: bool = False,
) -> float:
    """
    Compute confidence score from source and Places match quality.

    Applies: base_score → Places modifier → multi_source bonus → NONE cap → max cap.

    Args:
        source: Extraction source enum
        match_quality: Places match quality (EXACT, FUZZY, CATEGORY_ONLY, NONE)
        weights: Confidence weight config (base scores, modifiers, caps)
        corroborated: Whether extraction was validated by multiple sources

    Returns:
        Confidence score between 0.0 and 0.95

    """
    none_cap = weights.places_modifiers.get("NONE_CAP", 0.30)

    # Step 1: Base score from source
    base = weights.base_scores.get(source.value, 0.60)

    # Step 2: Places modifier
    if match_quality == PlacesMatchQuality.EXACT:
        score = base + weights.places_modifiers.get("EXACT", 0.20)
    elif match_quality == PlacesMatchQuality.FUZZY:
        score = base + weights.places_modifiers.get("FUZZY", 0.15)
    elif match_quality == PlacesMatchQuality.CATEGORY_ONLY:
        score = base + weights.places_modifiers.get("CATEGORY_ONLY", 0.10)
    else:  # NONE
        score = min(base, none_cap)

    # Step 3: Multi-source bonus (future enhancement)
    if corroborated:
        score += weights.multi_source_bonus

    # Step 4: Apply max cap
    return min(score, weights.max_score)


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
