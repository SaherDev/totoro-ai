"""Input/output types for the recall pipeline (feature 019, feature 027 M4).

`RecallFilters` mirrors `PlaceObject` 1:1 per ADR-056 (pulled forward from
M4): same top-level keys (`place_type`, `subcategory`, `tags_include`,
`source`) plus a nested `attributes: PlaceAttributes` holding cuisine,
price_hint, ambiance, dietary, good_for, and location_context.
Retrieval-specific fields (`max_distance_km`, `created_after`,
`created_before`) extend the base shape.

`RecallResult` wraps a `PlaceObject` with the `match_reason` string and
optional `relevance_score` (populated only in hybrid mode).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from totoro_ai.core.places.models import PlaceAttributes, PlaceObject


@dataclass
class RecallFilters:
    """Retrieval filters mirroring `PlaceObject` structure (ADR-056).

    Top-level keys match `PlaceObject` 1:1; attribute-level signals nest
    under `attributes`, matching `PlaceObject.attributes`. Retrieval-time
    constraints (`max_distance_km`, `created_after`, `created_before`)
    extend this shape.
    """

    place_type: str | None = None
    subcategory: str | None = None
    source: str | None = None
    tags_include: list[str] | None = None
    attributes: PlaceAttributes | None = None
    # Retrieval-specific constraints (not on PlaceObject)
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
