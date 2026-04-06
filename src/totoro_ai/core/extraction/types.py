"""New cascade types — zero dependencies on existing extraction modules.

These types coexist with the legacy ExtractionResult (result.py) until Run 3.
Import from totoro_ai.core.extraction.types to get these new types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ExtractionLevel(Enum):
    """Enricher levels that produce CandidatePlace objects.

    Only levels that create candidates are listed here. Caption enrichers
    (oEmbed, yt-dlp) and the validator (Google Places) are excluded.
    """

    EMOJI_REGEX = "emoji_regex"
    LLM_NER = "llm_ner"
    SUBTITLE_CHECK = "subtitle_check"
    WHISPER_AUDIO = "whisper_audio"
    VISION_FRAMES = "vision_frames"


@dataclass
class CandidatePlace:
    """Unvalidated place candidate produced by an enricher."""

    name: str
    city: str | None
    cuisine: str | None
    source: ExtractionLevel
    corroborated: bool = False


@dataclass
class ExtractionContext:
    """Shared mutable state threaded through all enrichers.

    Mutation rules:
    - caption and transcript are first-write-wins; once set, no enricher may overwrite.
    - candidates is append-only during enrichment.
    - pending_levels is set once by dispatch_background() (Run 2).
    """

    url: str | None
    user_id: str
    supplementary_text: str = ""
    caption: str | None = None
    transcript: str | None = None
    candidates: list[CandidatePlace] = field(default_factory=list)
    pending_levels: list[ExtractionLevel] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Validated, scored result from GooglePlacesValidator.

    NOTE: This is a new dataclass. The legacy ExtractionResult(BaseModel) in
    result.py remains unchanged until Run 3. Import disambiguation:
    - New type: from totoro_ai.core.extraction.types import ExtractionResult
    - Legacy type: from totoro_ai.core.extraction.result import ExtractionResult
    """

    place_name: str
    address: str | None
    city: str | None
    cuisine: str | None
    confidence: float
    resolved_by: ExtractionLevel
    corroborated: bool
    external_provider: str | None
    external_id: str | None


@dataclass
class ProvisionalResponse:
    """Returned when Phase 2 validation finds nothing and Phase 3 fires."""

    extraction_status: str
    confidence: float
    message: str
    pending_levels: list[ExtractionLevel] = field(default_factory=list)


@dataclass
class ExtractionPending:
    """Typed domain event for background dispatch (ADR-043)."""

    user_id: str
    url: str | None
    pending_levels: list[ExtractionLevel]
    context: ExtractionContext
