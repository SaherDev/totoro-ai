"""Consult service — place recommendation pipeline (feature 019, ADR-058).

Every "place" flowing between pipeline nodes is a `PlaceObject`. The pipeline
dedupes by `provider_id` (preferred) or `place_id`, enriches the combined
candidate set once via `PlacesService.enrich_batch(geo_only=False)`, and
returns candidates in source order (saved first, discovered second).

RankingService deleted per ADR-058 — agent-driven ranking is deferred.
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
    map_google_place_to_place_object,
)
from totoro_ai.core.intent.intent_parser import IntentParser
from totoro_ai.core.places import PlacesClient, PlacesService
from totoro_ai.core.places.models import PlaceObject
from totoro_ai.core.recall.service import RecallService
from totoro_ai.core.taste.regen import format_summary_for_agent
from totoro_ai.core.taste.schemas import Chip, ChipStatus, SummaryLine
from totoro_ai.core.taste.service import TasteModelService
from totoro_ai.core.utils.geo import haversine_m
from totoro_ai.db.repositories.recommendation_repository import (
    NullRecommendationRepository,
    RecommendationRepository,
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
        memory_service: UserMemoryService,
        taste_service: TasteModelService,
        recommendation_repo: RecommendationRepository | None = None,
    ) -> None:
        self._intent_parser = intent_parser
        self._recall_service = recall_service
        self._places_client = places_client
        self._places_service = places_service
        self._memory = memory_service
        self._taste_service = taste_service
        self._recommendation_repo: RecommendationRepository = (
            recommendation_repo
            if recommendation_repo is not None
            else NullRecommendationRepository()
        )

    async def consult(
        self,
        user_id: str,
        query: str,
        location: Location | None = None,
        signal_tier: str = "active",
    ) -> ConsultResponse:
        memory_list = await self._memory.load_memories(user_id)
        user_memories = "\n".join(memory_list) if memory_list else None
        logger.info("Loaded %d memories for user %s", len(memory_list), user_id)

        taste_profile = await self._taste_service.get_taste_profile(user_id)
        taste_summary: str | None = None
        if taste_profile and taste_profile.taste_profile_summary:
            lines = [
                SummaryLine.model_validate(item) if isinstance(item, dict) else item
                for item in taste_profile.taste_profile_summary
            ]
            taste_summary = format_summary_for_agent(lines)
            logger.info(
                "Loaded taste profile for user %s: %d lines, %d chips",
                user_id,
                len(lines),
                len(taste_profile.chips),
            )

        from totoro_ai.core.config import get_config as _get_config

        _config = _get_config()
        logger.info("Signal tier for user %s: %s", user_id, signal_tier)

        intent = await self._intent_parser.parse(
            query,
            user_memories=user_memories,
            taste_summary=taste_summary,
        )
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

        # Step 6: Return in source order (saved first, discovered second).
        # ADR-058: RankingService deleted. Agent-driven ranking is deferred.
        # Feature 023: warming tier enforces a config-driven discovered/saved
        # candidate-count blend on top of the source-order slice.

        # Active tier (023): filter out candidates matching any rejected chip
        # before slicing, and surface confirmed chips to reasoning_steps so a
        # future agent can consume them.
        if signal_tier == "active" and taste_profile is not None:
            confirmed_chips = [
                c for c in taste_profile.chips if c.status == ChipStatus.CONFIRMED
            ]
            rejected_chips = [
                c for c in taste_profile.chips if c.status == ChipStatus.REJECTED
            ]
            if rejected_chips:
                before = len(enriched_places)
                enriched_places = [
                    p
                    for p in enriched_places
                    if not any(_place_matches_chip(p, chip) for chip in rejected_chips)
                ]
                reasoning_steps.append(
                    ReasoningStep(
                        step="active_rejected_filter",
                        summary=(
                            f"Filtered {before - len(enriched_places)}/{before} "
                            "candidates matching rejected chips"
                        ),
                    )
                )
            if confirmed_chips:
                reasoning_steps.append(
                    ReasoningStep(
                        step="active_confirmed_signals",
                        summary=", ".join(c.label for c in confirmed_chips),
                    )
                )

        if not enriched_places:
            raise NoMatchesError(query)

        total_cap = _config.consult.total_cap
        if signal_tier == "warming":
            saved_cap = round(total_cap * _config.taste_model.warming_blend.saved)
            discovered_cap = total_cap - saved_cap
            saved_pool = [
                p
                for p in enriched_places
                if sources_by_place_id.get(p.place_id) == "saved"
            ][:saved_cap]
            discovered_pool = [
                p
                for p in enriched_places
                if sources_by_place_id.get(p.place_id) == "discovered"
            ][:discovered_cap]
            top = (saved_pool + discovered_pool)[:total_cap]
            reasoning_steps.append(
                ReasoningStep(
                    step="warming_blend",
                    summary=(
                        f"discovered={len(discovered_pool)}, saved={len(saved_pool)}"
                    ),
                )
            )
        else:
            top = enriched_places[:total_cap]

        results = [
            ConsultResult(
                place=place,
                source=sources_by_place_id.get(place.place_id, "discovered"),
            )
            for place in top
        ]

        reasoning_steps.append(
            ReasoningStep(
                step="response",
                summary=(
                    f"Returning {len(top)} candidates in source order "
                    "(ranking deferred per ADR-058)"
                ),
            )
        )

        recommendation_id = await self._persist_recommendation(
            user_id, query, reasoning_steps, results
        )

        response = ConsultResponse(
            recommendation_id=recommendation_id,
            results=results,
            reasoning_steps=reasoning_steps,
        )

        return response

    async def _persist_recommendation(
        self,
        user_id: str,
        query: str,
        reasoning_steps: list[ReasoningStep],
        results: list[ConsultResult],
    ) -> str | None:
        try:
            from totoro_ai.db.models import Recommendation

            # Persist only Tier 1 place fields — Tier 2 (geo) and Tier 3
            # (enrichment) live in Redis and are re-fetched on demand, so
            # storing them here would duplicate mutable cache state.
            tier1_results = [
                ConsultResult(
                    place=result.place.to_tier1(),
                    source=result.source,
                )
                for result in results
            ]

            # Build the response dict for JSONB storage. `mode="json"`
            # serializes datetimes to ISO strings and enums to values.
            response_data = ConsultResponse(
                recommendation_id=None,
                results=tier1_results,
                reasoning_steps=reasoning_steps,
            ).model_dump(mode="json")

            rec = Recommendation(
                user_id=user_id,
                query=query,
                response=response_data,
            )
            await self._recommendation_repo.save(rec)
            return str(rec.id)
        except Exception as exc:
            logger.warning(
                "Failed to persist recommendation for user %s: %s", user_id, exc
            )
            return None


def _place_matches_chip(place: PlaceObject, chip: Chip) -> bool:
    """Return True if the chip's (source_field, source_value) matches this place.

    Walks the chip's dotted `source_field` path against the place's
    attribute tree. Used in active-tier rejected-chip filtering (feature 023).

    Supported `source_field` prefixes:
    - "source"                      → place.source enum value
    - "subcategory.<place_type>"    → matches when place.subcategory == value
      and place.place_type matches the sub-path
    - "attributes.<name>"           → walks PlaceAttributes / LocationContext
    - "attributes.location_context.<city|neighborhood|country>" → location context

    Returns False on any lookup miss — the chip simply doesn't apply.
    """
    parts = chip.source_field.split(".")
    target = chip.source_value

    if parts == ["source"]:
        if place.source is None:
            return False
        return place.source.value == target

    if len(parts) == 2 and parts[0] == "subcategory":
        expected_place_type = parts[1]
        return (
            place.place_type.value == expected_place_type
            and place.subcategory == target
        )

    if parts[0] == "attributes":
        attrs: object = place.attributes
        for segment in parts[1:]:
            if attrs is None:
                return False
            attrs = getattr(attrs, segment, None)
        if attrs is None:
            return False
        return attrs == target

    return False


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
