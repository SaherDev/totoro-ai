"""Single source of truth for mapping a URL to a `PlaceSource`."""

from __future__ import annotations

from totoro_ai.core.places import PlaceSource


def source_from_url(url: str | None) -> PlaceSource | None:
    """Return the `PlaceSource` for a URL, or `None` for "no source".

    `None` is returned in two distinct cases:
    - `url is None` — caller passed nothing.
    - URL host doesn't map to any supported platform (e.g. a blog
      post, a generic short link). The service distinguishes the two
      by checking the original `url` value: a URL with `source is None`
      is an unsupported URL and gets rejected with a clear message
      before the cascade runs.

    Supported sources: TikTok, Instagram, YouTube, Google Maps.
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
    if (
        "maps.app.goo.gl" in lowered
        or "goo.gl/maps" in lowered
        or "google.com/maps" in lowered
        or "maps.google.com" in lowered
    ):
        return PlaceSource.google_maps
    return None
