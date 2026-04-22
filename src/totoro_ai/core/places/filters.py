"""Shared filter types for recall / consult / agent tools (feature 028 M4).

`PlaceFilters` mirrors `PlaceObject` 1:1 per ADR-056. `RecallFilters`
and `ConsultFilters` extend it with the retrieval-specific and
discovery-specific fields they each need.

`RecallFilters` lives in `core/recall/types.py` (imports and extends
`PlaceFilters` from here); `ConsultFilters` is declared here as a
sibling of `PlaceFilters`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from totoro_ai.core.places.models import (
    PlaceAttributes,
    PlaceSource,
    PlaceType,
)


class PlaceFilters(BaseModel):
    """Shared filter base mirroring `PlaceObject` (ADR-056). All fields optional."""

    place_type: PlaceType | None = None
    subcategory: str | None = None
    tags_include: list[str] | None = None
    attributes: PlaceAttributes | None = None
    source: PlaceSource | None = None

    model_config = ConfigDict(extra="forbid")


class ConsultFilters(PlaceFilters):
    """Discovery-time filter — adds geographic search bounds only.

    Kept provider-agnostic: no Google-specific passthrough. Live-constraint
    filtering (open-now, price gating) is deferred until the agent actually
    needs it — can be added later as typed fields on this class.
    """

    radius_m: int | None = None
    search_location_name: str | None = None


__all__ = ["PlaceFilters", "ConsultFilters"]
