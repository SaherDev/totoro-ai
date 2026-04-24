"""Single source of truth for mapping a URL to a `PlaceSource`."""

from __future__ import annotations

from totoro_ai.core.places import PlaceSource


def source_from_url(url: str | None) -> PlaceSource | None:
    """Return the `PlaceSource` for a URL, or `None` when no URL is given.

    Returns `PlaceSource.link` for URLs whose host doesn't map to a
    specific platform — i.e. "we have a URL but no recognized source".
    Enrichers that only support specific platforms should treat `link`
    as unsupported and short-circuit.
    """
    if url is None:
        return None
    lowered = url.lower()
    if "tiktok.com" in lowered:
        return PlaceSource.tiktok
    if "instagram.com" in lowered:
        return PlaceSource.instagram
    if "youtube.com" in lowered or "youtu.be" in lowered:
        return PlaceSource.youtube
    return PlaceSource.link
