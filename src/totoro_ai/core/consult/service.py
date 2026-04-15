"""Consult service — 6-step place recommendation pipeline (feature 019).

Every "place" flowing between pipeline nodes is a `PlaceObject`. The pipeline
dedupes by `provider_id` (preferred) or `place_id`, enriches the combined
candidate set once via `PlacesService.enrich_batch(geo_only=False)`, ranks
via `RankingService`, and builds the `ConsultResponse` from the top
`ScoredPlace`s. No parallel-array joins over `get_batch`: ranking scores
travel alongside the place in `ScoredPlace`, and the response builder
reads from the single object.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from totoro_ai.api.schemas.consult import (
    ConsultResponse,
    ConsultResult,
    Location,
    ReasoningStep,
)
from totoro_ai.core.consult.types import (
    NoMatchesError,
    ScoredPlace,
    map_google_place_to_place_object,
)
from totoro_ai.core.intent.intent_parser import IntentParser
from totoro_ai.core.places import PlacesClient, PlacesService
from totoro_ai.core.places.models import PlaceObject
from totoro_ai.core.ranking.service import RankingService
from totoro_ai.core.recall.service import RecallService
from totoro_ai.core.taste.service import TasteModelService
from totoro_ai.core.utils.geo import haversine_m
from totoro_ai.db.repositories.consult_log_repository import (
    ConsultLogRepository,
    NullConsultLogRepository,
)

if TYPE_CHECKING:
    from totoro_ai.core.memory.service import UserMemoryService

logger = logging.getLogger(__name__)


class ConsultService:
    """6-step place recommendation pipeline (PlaceObject-first)."""

    def __init__(
        self,
        intent_parser: IntentParser,
        recall_service: RecallService,
        places_client: PlacesClient,
        places_service: PlacesService,
        taste_service: TasteModelService,
        ranking_service: RankingService,
        memory_service: UserMemoryService,
        consult_log_repo: ConsultLogRepository | None = None,
    ) -> None:
        self._intent_parser = intent_parser
        self._recall_service = recall_service
        self._places_client = places_client
        self._places_service = places_service
        self._taste_service = taste_service
        self._ranking_service = ranking_service
        self._memory = memory_service
        self._consult_log_repo: ConsultLogRepository = (
            consult_log_repo
            if consult_log_repo is not None
            else NullConsultLogRepository()
        )

    async def consult(
        self,
        user_id: str,
        query: str,
        location: Location | None = None,
    ) -> ConsultResponse:
        user_memories = await self._memory.load_memories(user_id)
        logger.info("Loaded %d memories for user %s", len(user_memories), user_id)

        intent = await self._intent_parser.parse(query, user_memories=user_memories)
        logger.info("Parsed intent for user %s: %s", user_id, intent.model_dump())

        if intent.search.search_location_name:
            location_bias = (
                {"lat": location.lat, "lng": location.lng} if location else None
            )
            intent.search.search_location = await self._places_client.geocode(
                intent.search.search_location_name, location_bias=location_bias
            )
        if intent.search.search_location is None and location:
            intent.search.search_location = {"lat": location.lat, "lng": location.lng}

        from totoro_ai.core.config import get_config

        config = get_config()
        if intent.search.radius_m is None:
            intent.search.radius_m = config.consult.default_radius_m

        reasoning_steps: list[ReasoningStep] = []

        # Step 2: Retrieve saved places via RecallService.
        search_query = intent.search.enriched_query or query
        recall_response = await self._recall_service.run(search_query, user_id)
        saved_places: list[PlaceObject] = []

        for recall_result in recall_response.results:
            place = recall_result.place

            if (
                intent.search.search_location
                and place.lat is not None
                and place.lng is not None
            ):
                distance_m = haversine_m(
                    intent.search.search_location["lat"],
                    intent.search.search_location["lng"],
                    place.lat,
                    place.lng,
                )
                if distance_m > intent.search.radius_m:
                    continue

            saved_places.append(place)

        reasoning_steps.append(
            ReasoningStep(
                step="retrieval",
                summary=(
                    f"Retrieved {len(recall_response.results)} saved places, "
                    f"{len(saved_places)} after filtering"
                ),
            )
        )

        # Step 3: Discover external candidates via Google Places.
        discovered_places: list[PlaceObject] = []
        discovery_filters = dict(intent.search.discovery_filters)
        discovery_filters["keyword"] = intent.search.enriched_query or query

        if intent.search.search_location:
            try:
                discovery_results = await self._places_client.discover(
                    intent.search.search_location,
                    discovery_filters | {"radius": intent.search.radius_m},
                )
                for google_result in discovery_results:
                    discovered_places.append(
                        map_google_place_to_place_object(google_result)
                    )
                reasoning_steps.append(
                    ReasoningStep(
                        step="discovery",
                        summary=(
                            f"Found {len(discovered_places)} external candidates "
                            "via Google Places"
                        ),
                    )
                )
            except RuntimeError:
                reasoning_steps.append(
                    ReasoningStep(
                        step="discovery",
                        summary="External discovery skipped (provider unavailable)",
                    )
                )
        else:
            reasoning_steps.append(
                ReasoningStep(
                    step="discovery",
                    summary="Discovery skipped (no location context)",
                )
            )

        # Step 4: Dedupe by provider_id first, fall back to place_id.
        deduped_places, sources_by_place_id = _dedupe_places(
            saved_places, discovered_places
        )

        # Step 4.5: Enrich candidates with Tier 2 + Tier 3 data. Saved
        # places get priority in the fetch cap — if the deduped pool
        # exceeds `max_enrichment_batch`, the user's own saved places
        # are guaranteed to be enriched and discovered candidates take
        # the remaining budget.
        saved_priority_pids = {
            p.provider_id for p in saved_places if p.provider_id is not None
        }
        enriched_places = (
            await self._places_service.enrich_batch(
                deduped_places,
                geo_only=False,
                priority_provider_ids=saved_priority_pids,
            )
            if deduped_places
            else []
        )

        # Step 5: Validation (opennow) — if present in intent.
        validate_candidates = bool(
            intent.search.discovery_filters.get("opennow", False)
        )
        if validate_candidates and saved_places:
            validated: list[PlaceObject] = []
            for place in enriched_places:
                if sources_by_place_id.get(place.place_id) == "discovered":
                    validated.append(place)
                    continue
                try:
                    if await self._places_client.validate(
                        place, intent.search.discovery_filters
                    ):
                        validated.append(place)
                except RuntimeError:
                    pass
            reasoning_steps.append(
                ReasoningStep(
                    step="validation",
                    summary=(
                        f"Validated {len(validated)}/{len(enriched_places)} candidates "
                        "against constraints"
                    ),
                )
            )
            enriched_places = validated
        elif not validate_candidates:
            reasoning_steps.append(
                ReasoningStep(
                    step="validation",
                    summary="Validation skipped (no live constraints in query)",
                )
            )
        else:
            reasoning_steps.append(
                ReasoningStep(
                    step="validation",
                    summary=(
                        "Validation skipped (no saved candidates to validate — "
                        "open now enforced via discovery filters)"
                    ),
                )
            )

        # Step 6: Rank.
        taste_vector = await self._taste_service.get_taste_vector(user_id)
        ranked: list[ScoredPlace] = self._ranking_service.rank(
            enriched_places,
            taste_vector,
            intent.search.search_location,
            sources_by_place_id=sources_by_place_id,
        )

        reasoning_steps.append(
            ReasoningStep(
                step="ranking",
                summary=f"Ranked {len(ranked)} candidates using taste model",
            )
        )

        top = ranked[:3]
        if not top:
            raise NoMatchesError(query)

        results = [
            ConsultResult(
                place=sp.place,
                confidence=round(sp.score, 4),
                source=sp.source,
            )
            for sp in top
        ]

        reasoning_steps.append(
            ReasoningStep(
                step="response",
                summary=f"Selected {len(top)} final recommendations",
            )
        )

        response = ConsultResponse(
            results=results,
            reasoning_steps=reasoning_steps,
        )

        await self._persist_consult_log(user_id, query, response)
        return response

    async def _persist_consult_log(
        self,
        user_id: str,
        query: str,
        response: ConsultResponse,
    ) -> None:
        try:
            from totoro_ai.db.models import ConsultLog

            # `mode="json"` serializes every field to a primitive JSON
            # type — datetimes become ISO strings, enums become their
            # values, etc. — so the dict is safe to hand to SQLAlchemy's
            # JSONB column. The previous default `model_dump()` worked
            # when the response held only strings, but the new shape
            # carries full PlaceObject rows with `created_at: datetime`.
            log = ConsultLog(
                user_id=user_id,
                query=query,
                response=response.model_dump(mode="json"),
                intent="consult",
            )
            await self._consult_log_repo.save(log)
        except Exception as exc:
            logger.warning(
                "Failed to persist consult log for user %s: %s", user_id, exc
            )



def _dedupe_places(
    saved: list[PlaceObject], discovered: list[PlaceObject]
) -> tuple[list[PlaceObject], dict[str, str]]:
    """Dedupe saved + discovered places by provider_id, then place_id.

    Returns the ordered deduplicated list and a `place_id → "saved"|"discovered"`
    map so the ranker can apply the source-boost per place without a parallel
    array.
    """
    seen_provider_ids: set[str] = set()
    seen_place_ids: set[str] = set()
    deduped: list[PlaceObject] = []
    sources: dict[str, str] = {}

    def _push(place: PlaceObject, source: str) -> None:
        if place.provider_id is not None:
            if place.provider_id in seen_provider_ids:
                return
            seen_provider_ids.add(place.provider_id)
            seen_place_ids.add(place.place_id)
            deduped.append(place)
            sources[place.place_id] = source
            return
        if place.place_id in seen_place_ids:
            return
        seen_place_ids.add(place.place_id)
        deduped.append(place)
        sources[place.place_id] = source

    for place in saved:
        _push(place, "saved")
    for place in discovered:
        _push(place, "discovered")

    return deduped, sources
