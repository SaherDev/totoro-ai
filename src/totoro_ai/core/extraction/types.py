"""Shared types for the extraction cascade (ADR-054 / feature 019).

The "one shape everywhere" rule applies here: `CandidatePlace` and
`ValidatedCandidate` both wrap a `PlaceCreate` instead of carrying a
parallel set of loose fields. Extraction-only metadata (source level,
corroboration, signals, confidence, resolved_by) lives as sidecar fields
on the wrappers — everything else belongs on the `PlaceCreate` itself.

`PlaceCreate` and `PlaceObject` are re-exported so callers that imported
them from this module continue to resolve during the migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from totoro_ai.core.places import PlaceCreate, PlaceObject

__all__ = [
    "ExtractionLevel",
    "CandidatePlace",
    "ExtractionContext",
    "ValidatedCandidate",
    # Re-exported from core.places for legacy import paths.
    "PlaceCreate",
    "PlaceObject",
]


class ExtractionLevel(Enum):
    """Enricher levels that produce CandidatePlace objects."""

    EMOJI_REGEX = "emoji_regex"
    LLM_NER = "llm_ner"
    SUBTITLE_CHECK = "subtitle_check"
    WHISPER_AUDIO = "whisper_audio"
    VISION_FRAMES = "vision_frames"


@dataclass
class CandidatePlace:
    """Pre-validation wrapper around a `PlaceCreate`.

    Enrichers build a `PlaceCreate` with whatever they can derive from the
    source content (name, type, attributes, location_context, …) and wrap
    it here with the extraction-cascade metadata the validator and dedup
    passes need. `provider` and `external_id` on the inner `PlaceCreate`
    are left `None` until the validator runs.
    """

    place: PlaceCreate
    source: ExtractionLevel
    corroborated: bool = False
    signals: list[str] = field(default_factory=list)


@dataclass
class ExtractionContext:
    """Shared mutable state threaded through all enrichers."""

    url: str | None
    user_id: str
    supplementary_text: str = ""
    caption: str | None = None
    transcript: str | None = None
    candidates: list[CandidatePlace] = field(default_factory=list)
    platform: str | None = None
    title: str | None = None
    hashtags: list[str] = field(default_factory=list)
    location_tag: str | None = None


@dataclass
class ValidatedCandidate:
    """Post-validation wrapper — same `PlaceCreate`, now with `provider` +
    `external_id` filled in by the validator.

    `confidence`, `resolved_by`, and `corroborated` are extraction-internal
    fields. `match_lat`, `match_lng`, `match_address` carry the Tier 2 geo
    data Google Places returned from `validate_place` so the persistence
    layer can write it to `PlacesCache` after the Tier 1 row is created
    (ADR-057 follow-up). All three geo fields are optional — `None` when
    Google returned NONE-quality or the validator was bypassed.
    """

    place: PlaceCreate
    confidence: float
    resolved_by: ExtractionLevel
    corroborated: bool = False
    match_lat: float | None = None
    match_lng: float | None = None
    match_address: str | None = None
