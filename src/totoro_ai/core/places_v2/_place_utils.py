"""Shared utilities for constructing PlaceObject from PlaceCore + cache."""

from __future__ import annotations

from .models import PlaceCore, PlaceObject


def overlay_with_cache(
    cores: list[PlaceCore],
    cached: dict[str, PlaceObject],
) -> list[PlaceObject]:
    """Merge DB cores with cached live fields (rating, hours, phone, etc.).

    For each core, if a matching cached PlaceObject exists the live fields are
    copied over. Cores with no cache entry are returned as bare PlaceObjects.
    """
    result: list[PlaceObject] = []
    for core in cores:
        if core.provider_id and core.provider_id in cached:
            cached_obj = cached[core.provider_id]
            obj = PlaceObject(
                **core.model_dump(),
                rating=cached_obj.rating,
                hours=cached_obj.hours,
                phone=cached_obj.phone,
                website=cached_obj.website,
                popularity=cached_obj.popularity,
                cached_at=cached_obj.cached_at,
            )
        else:
            obj = PlaceObject(**core.model_dump())
        result.append(obj)
    return result
