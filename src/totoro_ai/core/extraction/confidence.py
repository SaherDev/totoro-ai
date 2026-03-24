"""Extraction source classification and confidence scoring logic."""

from enum import Enum

from totoro_ai.core.config import ConfidenceWeights
from totoro_ai.core.extraction.places_client import PlacesMatchQuality


class ExtractionSource(str, Enum):
    """Source of extraction — determines base confidence score."""

    CAPTION = "CAPTION"        # TikTok oEmbed caption (current)
    PLAIN_TEXT = "PLAIN_TEXT"  # Plain text input (current)
    SPEECH = "SPEECH"          # Whisper transcription (will be supported later)
    OCR = "OCR"                # Frame OCR (will be supported later)


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
