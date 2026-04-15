"""Input/output types for the recall pipeline (feature 019, Session 2 Addendum).

`RecallFilters` is the unified filter set both the repository and the service
speak. `RecallResult` wraps a `PlaceObject` with the `match_reason` string
and optional `relevance_score` (populated only in hybrid mode).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from totoro_ai.core.places.models import PlaceObject


@dataclass
class RecallFilters:
    place_type: str | None = None
    subcategory: str | None = None
    source: str | None = None
    tags_include: list[str] | None = None
    cuisine: str | None = None
    price_hint: str | None = None
    ambiance: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    country: str | None = None
    max_distance_km: float | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


@dataclass
class RecallResult:
    place: PlaceObject
    match_reason: str
    relevance_score: float | None = None
    """Score scale depends on score_type — rrf scores are typically 0.01–0.03,
    ts_rank scores are 0–1. Never compare across types."""

    score_type: Literal["rrf", "ts_rank"] | None = None


__all__ = ["RecallFilters", "RecallResult"]

# `field` imported for symmetry with other dataclass modules; reserved for
# future mutable defaults.
_ = field
