"""places_v2 — standalone places library.

Public surface: models, protocols, concrete implementations, services.
"""

from .cache import RedisPlacesCache
from .google_client import GooglePlacesClient
from .models import (
    HoursDict,
    LocationContext,
    PlaceAttributes,
    PlaceCore,
    PlaceCoreUpsertedEvent,
    PlaceObject,
    PlaceQuery,
    PlaceSource,
    SavedPlaceView,
    UserPlace,
)
from .places_repo import PlacesRepo
from .protocols import (
    PlaceEventDispatcherProtocol,
    PlacesCacheProtocol,
    PlacesClientProtocol,
    PlacesRepoProtocol,
    UserPlacesRepoProtocol,
)
from .search_service import PlacesSearchService
from .upsert_service import PlaceUpsertService
from .user_places_repo import UserPlacesRepo
from .user_places_service import UserPlacesService

__all__ = [
    # models
    "HoursDict",
    "LocationContext",
    "PlaceAttributes",
    "PlaceCore",
    "PlaceCoreUpsertedEvent",
    "PlaceObject",
    "PlaceQuery",
    "PlaceSource",
    "SavedPlaceView",
    "UserPlace",
    # protocols
    "PlaceEventDispatcherProtocol",
    "PlacesCacheProtocol",
    "PlacesClientProtocol",
    "PlacesRepoProtocol",
    "UserPlacesRepoProtocol",
    # implementations
    "PlacesRepo",
    "UserPlacesRepo",
    "RedisPlacesCache",
    "GooglePlacesClient",
    # services
    "PlacesSearchService",
    "PlaceUpsertService",
    "UserPlacesService",
]
