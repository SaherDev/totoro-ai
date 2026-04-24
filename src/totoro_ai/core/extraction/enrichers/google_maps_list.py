"""Google Maps shared-list enricher (Apify-backed).

Google Maps shared lists (`maps.app.goo.gl/<short>` that resolves to a
URL with `!3e3` in its data parameter) cannot be scraped from plain
HTML — the page is fully client-side rendered. We delegate to the
Apify `parseforge/google-maps-shared-list-scraper` actor, which runs
the scrape and returns each list entry with its name, lat/lng,
rating, and category.

The actor returns a Google Maps internal FID for each place
(`0x...:0x...`), which is **not** the same as the Places API Place
ID (`ChIJ...`). We deliberately drop the FID and let
`GooglePlacesValidator` discover the canonical Place ID downstream
via name + city — this keeps `external_id` consistent with what the
rest of the system uses for dedup. Coords from the actor are not
plumbed through today because `PlaceCreate` doesn't carry raw
lat/lng; the validator finds places from name alone.

The actor's default proxy (`useApifyProxy: true` → residential) is
a paid feature on Apify. We pass `useApifyProxy: false` to skip it;
the actor falls back to its own scraping path.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from totoro_ai.core.config import get_env
from totoro_ai.core.extraction.source_filtered_enricher import SourceFilteredEnricher
from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
)
from totoro_ai.core.places import (
    PlaceAttributes,
    PlaceCreate,
    PlaceSource,
    PlaceType,
)

logger = logging.getLogger(__name__)

_APIFY_ENDPOINT = (
    "https://api.apify.com/v2/acts/"
    "parseforge~google-maps-shared-list-scraper/run-sync-get-dataset-items"
)
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_PLACES = 100


class GoogleMapsListEnricher(SourceFilteredEnricher):
    """Pulls a Google Maps shared list via the Apify scraper actor.

    Gated to `PlaceSource.google_maps`. Skips silently when the Apify
    token isn't configured (no candidates appended; the rest of the
    cascade keeps running). Exceptions propagate to the surrounding
    `CircuitBreakerEnricher` so a degraded Apify doesn't keep retrying
    on every request.
    """

    def __init__(
        self,
        token: str | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(allowed_sources={PlaceSource.google_maps})
        # Lazy-resolve the token so tests can construct the enricher
        # without touching the env, but production callers can pass it
        # explicitly if they want.
        self._token = token
        self._timeout_seconds = timeout_seconds

    def _resolve_token(self) -> str | None:
        return self._token or get_env().APIFY_TOKEN

    async def _run(self, context: ExtractionContext) -> None:
        token = self._resolve_token()
        if not token:
            logger.info(
                "GoogleMapsListEnricher skipped — APIFY_TOKEN not configured "
                "(url=%s)",
                context.url,
            )
            return

        items = await self._fetch_list(context.url, token)  # type: ignore[arg-type]
        for item in items:
            candidate = self._item_to_candidate(item, context.user_id)
            if candidate is not None:
                context.candidates.append(candidate)

    async def _fetch_list(self, url: str, token: str) -> list[dict[str, Any]]:
        body = {
            "listUrls": [url],
            "outputFormat": "json",
            "maxPlacesPerList": _DEFAULT_MAX_PLACES,
            # Skip Apify's residential proxy — it's a paid-tier feature
            # and the actor falls back to a working scraping path
            # without it.
            "proxyConfiguration": {"useApifyProxy": False},
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _APIFY_ENDPOINT,
                params={"token": token},
                json=body,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            return []
        return data

    def _item_to_candidate(
        self, item: dict[str, Any], user_id: str
    ) -> CandidatePlace | None:
        name = item.get("name") or item.get("title")
        if not name:
            return None
        # `placeId` from Apify is a Google Maps FID (`0x...:0x...`), not
        # a Places API ChIJ Place ID. Drop it and let the validator
        # resolve the canonical ID downstream so external_id stays
        # consistent across all extraction paths.
        place = PlaceCreate(
            user_id=user_id,
            place_name=str(name),
            # Apify's payload mixes restaurants, attractions, etc. —
            # default to food_and_drink (dominant share-list type) and
            # let downstream classification refine if needed.
            place_type=PlaceType.food_and_drink,
            attributes=PlaceAttributes(),
        )
        return CandidatePlace(
            place=place,
            source=ExtractionLevel.GOOGLE_MAPS_LIST,
        )
