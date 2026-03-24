"""Extraction source classification and confidence scoring logic."""

from enum import Enum

from totoro_ai.core.config import load_yaml_config
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
    corroborated: bool = False,
) -> float:
    """
    Compute confidence score from source and Places match quality.

    Applies: base_score → Places modifier → multi_source bonus → NONE cap → max cap.

    Args:
        source: Extraction source enum
        match_quality: Places match quality (EXACT, FUZZY, CATEGORY_ONLY, NONE)
        corroborated: Whether extraction was validated by multiple sources

    Returns:
        Confidence score between 0.0 and 0.95

    """
    config = load_yaml_config(".local.yaml")
    weights = config.get("extraction", {}).get("confidence_weights", {})

    base_scores = weights.get("base_scores", {})
    places_modifiers = weights.get("places_modifiers", {})
    multi_source_bonus = weights.get("multi_source_bonus", 0.10)
    max_score = weights.get("max_score", 0.95)
    none_cap = weights.get("places_modifiers", {}).get("NONE_CAP", 0.30)

    # Step 1: Base score from source
    base = base_scores.get(source.value, 0.60)

    # Step 2: Places modifier
    if match_quality == PlacesMatchQuality.EXACT:
        modifier = places_modifiers.get("EXACT", 0.20)
        score = base + modifier
    elif match_quality == PlacesMatchQuality.FUZZY:
        modifier = places_modifiers.get("FUZZY", 0.15)
        score = base + modifier
    elif match_quality == PlacesMatchQuality.CATEGORY_ONLY:
        modifier = places_modifiers.get("CATEGORY_ONLY", 0.10)
        score = base + modifier
    else:  # NONE
        # Cap score when no Places match
        score = min(base, none_cap)

    # Step 3: Multi-source bonus (future enhancement)
    if corroborated:
        score += multi_source_bonus

    # Step 4: Apply max cap
    return min(score, max_score)
