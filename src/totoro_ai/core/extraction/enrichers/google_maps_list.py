"""Google Maps shared-list enricher (Apify-backed).

Google Maps shared lists (`maps.app.goo.gl/<short>` that resolves to a
URL with `!3e3` in its data parameter) cannot be scraped from plain
HTML — the page is fully client-side rendered. We delegate to the
Apify `parseforge/google-maps-shared-list-scraper` actor, which runs
its own browser pool and returns a JSON dataset with real Google
Place IDs.

Each list item comes back already identified (`placeId` is a
canonical `ChIJ...` Google Place ID), so we attach the provider /
external_id directly on the `PlaceCreate`. The validator still runs
downstream — it'll confirm the place exists and fill in geo data —
but it doesn't need to discover the identity.
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
    PlaceProvider,
    PlaceSource,
    PlaceType,
)

logger = logging.getLogger(__name__)

_APIFY_ENDPOINT = (
    "https://api.apify.com/v2/acts/"
    "parseforge~google-maps-shared-list-scraper/run-sync-get-dataset-items"
)
_DEFAULT_TIMEOUT_SECONDS = 60.0


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
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _APIFY_ENDPOINT,
                params={"token": token},
                json={"startUrls": [{"url": url}]},
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
        name = item.get("title") or item.get("name")
        if not name:
            return None
        place_id = item.get("placeId") or item.get("place_id")
        place = PlaceCreate(
            user_id=user_id,
            place_name=str(name),
            # Apify's payload mixes restaurants, attractions, etc. — the
            # NER prompt vocabulary doesn't apply here. Default to
            # food_and_drink (the dominant share-list type) and let the
            # validator + downstream classification refine if needed.
            place_type=PlaceType.food_and_drink,
            attributes=PlaceAttributes(),
            provider=PlaceProvider.google if place_id else None,
            external_id=str(place_id) if place_id else None,
        )
        return CandidatePlace(
            place=place,
            source=ExtractionLevel.GOOGLE_MAPS_LIST,
        )
