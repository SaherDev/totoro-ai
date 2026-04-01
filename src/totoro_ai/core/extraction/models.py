"""Core data models for the three-phase extraction pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ExtractionLevel(str, Enum):
    """Extraction levels that produce CandidatePlace objects.

    Caption enrichers (oEmbed, yt-dlp) and the validator (Google Places)
    are not in this enum because they never create CandidatePlace objects.
    """

    EMOJI_REGEX = "EMOJI_REGEX"
    LLM_NER = "LLM_NER"
    SUBTITLE_CHECK = "SUBTITLE_CHECK"
    WHISPER_AUDIO = "WHISPER_AUDIO"
    VISION_FRAMES = "VISION_FRAMES"


@dataclass
class CandidatePlace:
    """A candidate place found by an enricher, pending validation."""

    name: str
    city: str | None = None
    cuisine: str | None = None
    source: ExtractionLevel = ExtractionLevel.LLM_NER
    corroborated: bool = False


@dataclass
class ExtractionContext:
    """Mutable shared state passed through the enrichment pipeline.

    Enrichers mutate this context as side effects: populating caption,
    transcript, and appending to candidates.
    """

    url: str | None
    user_id: str
    supplementary_text: str = ""
    caption: str | None = None
    transcript: str | None = None
    candidates: list[CandidatePlace] = field(default_factory=list)
    pending_levels: list[ExtractionLevel] = field(default_factory=list)
