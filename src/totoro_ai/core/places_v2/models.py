"""Domain models for the places_v2 library.

Three core classes:
- PlaceCore: DB-side curated and locational data, shared across all users.
- PlaceObject: extends PlaceCore with Google-derived live fields (cache-only).
- UserPlace: per (user, place) pair.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlaceSource(str, Enum):
    tiktok = "tiktok"
    instagram = "instagram"
    youtube = "youtube"
    google_maps_list = "google_maps_list"
    manual = "manual"
    totoro = "totoro"


# weekday → list of "HH:MM-HH:MM" ranges, plus "timezone" key for IANA string
HoursDict: TypeAlias = dict[str, list[str] | str]


class LocationContext(BaseModel):
    """Location container used in PlaceQuery and optionally PlaceCore.attributes."""

    lat: float | None = None
    lng: float | None = None
    radius_m: int | None = None
    neighborhood: str | None = None
    city: str | None = None
    country: str | None = None

    model_config = ConfigDict(extra="forbid")


class PlaceAttributes(BaseModel):
    cuisine: str | None = None
    price_hint: str | None = None
    ambiance: str | None = None
    dietary: list[str] = Field(default_factory=list)
    good_for: list[str] = Field(default_factory=list)
    location_context: LocationContext | None = None


class PlaceQuery(BaseModel):
    """Structured search query. All fields optional; combine as needed.

    Callers compose filters explicitly — the library never parses freeform
    strings to determine intent.
    """

    text: str | None = None
    location: LocationContext | None = None
    tags: list[str] = Field(default_factory=list)
    cuisine: str | None = None
    price_hint: str | None = None


class PlaceCore(BaseModel):
    """Canonical place data. DB-side. Same for all users.

    Curated fields are mergeable on upsert. Locational fields are refreshable
    after a 30-day TTL wipe (Google ToS compliance).
    """

    # identity
    id: str | None = None
    provider_id: str | None = None  # namespaced, e.g. "google:ChIJ..."

    # core (mergeable)
    place_name: str
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    attributes: PlaceAttributes = Field(default_factory=PlaceAttributes)

    # location (Google-derived; wiped by nightly cron after 30 days per ToS)
    lat: float | None = None
    lng: float | None = None
    address: str | None = None

    # timestamps
    created_at: datetime | None = None
    refreshed_at: datetime | None = None


class PlaceObject(PlaceCore):
    """Full place: PlaceCore + Google-derived live fields. Cache-only for live half."""

    rating: float | None = None
    hours: HoursDict | None = None
    phone: str | None = None
    website: str | None = None
    popularity: int | None = None
    cached_at: datetime | None = None


class UserPlace(BaseModel):
    """One row per (user, place). Holds everything the user owns about this place."""

    user_place_id: str
    user_id: str
    place_id: str  # FK to PlaceCore.id

    needs_approval: bool = False
    visited: bool = False
    liked: bool | None = None

    note: str | None = None

    source: PlaceSource
    source_url: str | None = None

    saved_at: datetime
    visited_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_source(self) -> UserPlace:
        if self.source in (PlaceSource.manual, PlaceSource.totoro):
            if self.source_url is not None:
                raise ValueError(
                    f"source_url must be None when source is {self.source.value}"
                )
        else:
            if self.source_url is None:
                raise ValueError(
                    f"source_url is required when source is {self.source.value}"
                )
        return self


class SavedPlaceView(BaseModel):
    """List view combining a UserPlace with its underlying place data."""

    place: PlaceObject
    user_data: UserPlace


class PlaceCoreUpsertedEvent(BaseModel):
    """Emitted after a PlaceCore is inserted or updated."""

    place_core: PlaceCore
