"""Domain models for the places_v2 library.

Three core classes:
- PlaceCore: DB-side curated and locational data, shared across all users.
- PlaceObject: extends PlaceCore with Google-derived live fields (cache-only).
- UserPlace: per (user, place) pair.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlaceSource(str, Enum):
    tiktok = "tiktok"
    instagram = "instagram"
    youtube = "youtube"
    google_maps_list = "google_maps_list"
    manual = "manual"
    totoro = "totoro"


class PlaceCategory(str, Enum):
    # food & drink
    restaurant = "restaurant"
    cafe = "cafe"
    bar = "bar"
    pub = "pub"
    bakery = "bakery"
    dessert_shop = "dessert_shop"
    ice_cream_shop = "ice_cream_shop"
    street_food = "street_food"
    food_court = "food_court"
    food_market = "food_market"
    brewery = "brewery"
    winery = "winery"
    distillery = "distillery"
    tea_house = "tea_house"
    juice_bar = "juice_bar"
    # retail
    grocery_store = "grocery_store"
    supermarket = "supermarket"
    convenience_store = "convenience_store"
    shopping_mall = "shopping_mall"
    boutique = "boutique"
    bookstore = "bookstore"
    specialty_shop = "specialty_shop"
    farmers_market = "farmers_market"
    flea_market = "flea_market"
    night_market = "night_market"
    pharmacy = "pharmacy"
    electronics_store = "electronics_store"
    # culture / sightseeing
    museum = "museum"
    art_gallery = "art_gallery"
    historical_site = "historical_site"
    monument = "monument"
    temple = "temple"
    church = "church"
    mosque = "mosque"
    shrine = "shrine"
    landmark = "landmark"
    viewpoint = "viewpoint"
    # entertainment
    theme_park = "theme_park"
    amusement_park = "amusement_park"
    zoo = "zoo"
    aquarium = "aquarium"
    botanical_garden = "botanical_garden"
    cinema = "cinema"
    theater = "theater"
    concert_hall = "concert_hall"
    live_music_venue = "live_music_venue"
    nightclub = "nightclub"
    comedy_club = "comedy_club"
    karaoke = "karaoke"
    arcade = "arcade"
    bowling_alley = "bowling_alley"
    billiards_hall = "billiards_hall"
    # nature / outdoors
    park = "park"
    beach = "beach"
    hiking_trail = "hiking_trail"
    lake = "lake"
    river = "river"
    garden = "garden"
    campground = "campground"
    scenic_lookout = "scenic_lookout"
    # fitness / wellness
    gym = "gym"
    fitness_studio = "fitness_studio"
    yoga_studio = "yoga_studio"
    pilates_studio = "pilates_studio"
    spa = "spa"
    massage = "massage"
    hot_spring = "hot_spring"
    bathhouse = "bathhouse"
    salon = "salon"
    barber = "barber"
    # services / utilities
    atm = "atm"
    bank = "bank"
    post_office = "post_office"
    gas_station = "gas_station"
    parking = "parking"
    laundry = "laundry"
    # accommodation
    hotel = "hotel"
    hostel = "hostel"
    guesthouse = "guesthouse"
    bed_and_breakfast = "bed_and_breakfast"
    resort = "resort"
    vacation_rental = "vacation_rental"
    # transit
    airport = "airport"
    train_station = "train_station"
    metro_station = "metro_station"
    bus_terminal = "bus_terminal"
    ferry_terminal = "ferry_terminal"
    # sport / recreation
    stadium = "stadium"
    arena = "arena"
    sports_club = "sports_club"
    swimming_pool = "swimming_pool"
    climbing_gym = "climbing_gym"
    skate_park = "skate_park"
    golf_course = "golf_course"
    # work / study
    coworking_space = "coworking_space"
    library = "library"
    study_cafe = "study_cafe"


# weekday → list of "HH:MM-HH:MM" ranges, plus "timezone" key for IANA string
HoursDict: TypeAlias = dict[str, list[str] | str]


class LocationContext(BaseModel):
    """Location container used in PlaceQuery and optionally PlaceCore.attributes."""

    lat: float | None = None
    lng: float | None = None
    address: str | None = None
    radius_m: int | None = None
    neighborhood: str | None = None
    city: str | None = None
    country: str | None = None

    model_config = ConfigDict(extra="forbid")


class PlaceTag(BaseModel):
    type: str   # "cuisine" | "dietary" | "feature" | "service" | "atmosphere"
    value: str  # e.g. "Thai", "vegan", "outdoor_seating", "takeout", "cozy"
    source: str  # "google" | "llm" | "manual" | "tiktok" | ...


class PlaceAttributes(BaseModel):
    price_hint: str | None = None
    tags: list[PlaceTag] = Field(default_factory=list)


SortField = Literal["created_at", "refreshed_at", "place_name", "category"]


class PlaceQuery(BaseModel):
    """Structured search query. All fields optional, combined with AND."""

    place_name: str | None = None
    category: PlaceCategory | None = None
    # filter by tag values (all must be present, source/type ignored)
    tags: list[str] | None = None
    price_hint: str | None = None
    location: LocationContext | None = None

    # date range
    created_after: datetime | None = None
    created_before: datetime | None = None

    # ordering
    sort_by: SortField | None = None
    sort_desc: bool = True


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
    category: PlaceCategory | None = None
    attributes: PlaceAttributes = Field(default_factory=PlaceAttributes)

    # location (Google-derived; wiped by nightly cron after 30 days per ToS)
    location: LocationContext | None = None

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
    """Emitted after one or more PlaceCores are inserted or updated."""

    place_cores: list[PlaceCore]
