"""places_v2 — standalone places library.

Public surface: models, protocols, concrete implementations, services.
"""

from .cache import RedisPlacesCache
from .google_client import GooglePlacesClient
from .models import (
    HoursDict,
    LocationContext,
    PlaceCategory,
    PlaceCore,
    PlaceNameAlias,
    PlaceObject,
    PlaceQuery,
    PlaceSource,
    PlaceTag,
    SavedPlaceView,
    UserPlace,
)
from .place_wipe_service import PlaceWipeService
from .places_repo import PlacesRepo
from .protocols import (
    PlacesCacheProtocol,
    PlacesClientProtocol,
    PlacesRepoProtocol,
    PlacesSearchServiceProtocol,
    PlaceUpsertServiceProtocol,
    PlaceWipeServiceProtocol,
    UserPlacesRepoProtocol,
    UserPlacesServiceProtocol,
)
from .search_service import PlacesSearchService
from .tags import (
    AccessibilityTag,
    AtmosphereTag,
    CuisineTag,
    DietaryTag,
    FeatureTag,
    PriceTag,
    SeasonTag,
    ServiceTag,
    TagType,
    TagValue,
    TimeTag,
)
from .upsert_service import PlaceUpsertService
from .user_places_repo import UserPlacesRepo
from .user_places_service import UserPlacesService

__all__ = [
    # tag vocabulary
    "TagType",
    "CuisineTag",
    "DietaryTag",
    "FeatureTag",
    "AtmosphereTag",
    "ServiceTag",
    "PriceTag",
    "AccessibilityTag",
    "TimeTag",
    "SeasonTag",
    "TagValue",
    # models
    "HoursDict",
    "LocationContext",
    "PlaceCategory",
    "PlaceCore",
    "PlaceNameAlias",
    "PlaceObject",
    "PlaceQuery",
    "PlaceSource",
    "PlaceTag",
    "SavedPlaceView",
    "UserPlace",
    # protocols
    "PlacesCacheProtocol",
    "PlacesClientProtocol",
    "PlacesRepoProtocol",
    "PlacesSearchServiceProtocol",
    "PlaceUpsertServiceProtocol",
    "PlaceWipeServiceProtocol",
    "UserPlacesRepoProtocol",
    "UserPlacesServiceProtocol",
    # implementations
    "PlacesRepo",
    "UserPlacesRepo",
    "RedisPlacesCache",
    "GooglePlacesClient",
    # services
    "PlacesSearchService",
    "PlaceUpsertService",
    "PlaceWipeService",
    "UserPlacesService",
]
