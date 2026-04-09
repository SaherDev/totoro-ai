"""Consult service — 6-step place recommendation pipeline (ADR-049, ADR-050)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from totoro_ai.api.schemas.consult import (
    ConsultResponse,
    Location,
    PlaceResult,
    ReasoningStep,
)
from totoro_ai.core.consult.types import (
    Candidate,
    ExternalCandidateMapper,
    RecallResultToCandidateMapper,
)
from totoro_ai.core.intent.intent_parser import IntentParser
from totoro_ai.core.places import PlacesClient
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
    """6-step place recommendation pipeline.

    Phases:
    1. Parse intent from query
    2. Retrieve saved places matching query
    3. Discover external candidates via Places API
    4. Validate saved candidates (conditional)
    5. Rank all candidates
    6. Build response with top 3 + reasoning steps
    7. Persist consult log (write failure does not fail the response)
    """

    def __init__(
        self,
        intent_parser: IntentParser,
        recall_service: RecallService,
        places_client: PlacesClient,
        taste_service: TasteModelService,
        ranking_service: RankingService,
        memory_service: "UserMemoryService",
        consult_log_repo: ConsultLogRepository | None = None,
    ) -> None:
        """Initialize ConsultService with dependencies (ADR-019, ADR-038).

        Injects UserMemoryService for loading user facts during intent parsing.
        """
        self._intent_parser = intent_parser
        self._recall_service = recall_service
        self._places_client = places_client
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
        """Run the 6-step pipeline for place recommendations.

        Args:
            user_id: User identifier
            query: Natural language recommendation query
            location: Optional user location as {'lat': float, 'lng': float}

        Returns:
            ConsultResponse with primary + 2 alternatives + reasoning steps

        Raises:
            ValueError: If intent parsing fails (HTTP 500 from route handler)
        """
        # Load user memories for context injection (ADR-010)
        user_memories = await self._memory.load_memories(user_id)
        logger.info("Loaded %d memories for user %s", len(user_memories), user_id)

        # Step 1: Parse intent from query with user context, then resolve search location
        intent = await self._intent_parser.parse(query, user_memories=user_memories)
        logger.info("Parsed intent for user %s: %s", user_id, intent.model_dump())

        if intent.search_location_name:
            intent.search_location = await self._places_client.geocode(
                intent.search_location_name
            )
        if intent.search_location is None and location:
            intent.search_location = {"lat": location.lat, "lng": location.lng}

        # Update radius with config default if LLM returned null
        from totoro_ai.core.config import get_config

        config = get_config()
        if intent.radius is None:
            intent.radius = config.consult.radius_defaults.default

        # Build reasoning steps tracking
        reasoning_steps: list[ReasoningStep] = []

        # Step 2: Retrieve saved places
        recall_results = await self._recall_service.run(query, user_id)
        saved_candidates: list[Candidate] = []

        if recall_results.results:
            saved_mapper = RecallResultToCandidateMapper()
            for recall_result in recall_results.results:
                candidate = saved_mapper.map(recall_result)

                # Apply intent filters (price_range, radius)
                if intent.price_range and candidate.price_range != intent.price_range:
                    continue

                # Post-filter by distance if search_location available
                if intent.search_location and candidate.lat and candidate.lng:
                    distance_m = haversine_m(
                        intent.search_location["lat"],
                        intent.search_location["lng"],
                        candidate.lat,
                        candidate.lng,
                    )
                    if distance_m > intent.radius:
                        continue
                    candidate.distance = distance_m

                saved_candidates.append(candidate)

        reasoning_steps.append(
            ReasoningStep(
                step="retrieval",
                summary=f"Retrieved {len(recall_results.results)} saved places, {len(saved_candidates)} after filtering",
            )
        )

        # Step 3: Discover external candidates via Google Places API
        discovered_candidates: list[Candidate] = []

        if intent.search_location:
            try:
                discovery_results = await self._places_client.discover(
                    intent.search_location,
                    intent.discovery_filters | {"radius": intent.radius},
                )

                external_mapper = ExternalCandidateMapper()
                for google_result in discovery_results:
                    candidate = external_mapper.map(google_result)

                    # Compute distance from search_location
                    if candidate.lat and candidate.lng:
                        distance_m = haversine_m(
                            intent.search_location["lat"],
                            intent.search_location["lng"],
                            candidate.lat,
                            candidate.lng,
                        )
                        candidate.distance = distance_m

                    discovered_candidates.append(candidate)

                reasoning_steps.append(
                    ReasoningStep(
                        step="discovery",
                        summary=f"Found {len(discovered_candidates)} external candidates via Google Places",
                    )
                )
            except RuntimeError:
                # External provider failure: graceful fallback to saved candidates only
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

        # Step 4: Deduplication by external_id (when available), then place_id
        # When a saved and discovered candidate share the same external_id,
        # keep the saved version; otherwise deduplicate by place_id
        all_candidates = saved_candidates + discovered_candidates
        seen_place_ids = set()
        seen_external_ids = set()
        deduplicated: list[Candidate] = []

        for candidate in all_candidates:
            # Check external_id first (e.g., Google place_id for both saved and discovered)
            if candidate.external_id:
                if candidate.external_id not in seen_external_ids:
                    deduplicated.append(candidate)
                    seen_external_ids.add(candidate.external_id)
                    # Also track place_id to avoid duplicating via that path
                    seen_place_ids.add(candidate.place_id)
            # Fallback to place_id deduplication
            elif candidate.place_id not in seen_place_ids:
                deduplicated.append(candidate)
                seen_place_ids.add(candidate.place_id)

        # Step 5: Conditional validation of saved candidates
        validate_candidates = bool(intent.discovery_filters.get("opennow", False))
        if validate_candidates and saved_candidates:
            valid_candidates = []
            for candidate in saved_candidates:
                try:
                    is_valid = await self._places_client.validate(
                        candidate, intent.discovery_filters
                    )
                    if is_valid:
                        valid_candidates.append(candidate)
                except RuntimeError:
                    # Validation error: skip this candidate
                    pass

            reasoning_steps.append(
                ReasoningStep(
                    step="validation",
                    summary=f"Validated {len(valid_candidates)}/{len(saved_candidates)} saved places against constraints",
                )
            )

            # Filter all_candidates to only include validated saved or discovered
            deduplicated = [
                c
                for c in deduplicated
                if c.source == "discovered" or c in valid_candidates
            ]
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
                    summary="Validation skipped (no saved candidates to validate — open now enforced via discovery filters)",
                )
            )

        # Step 6: Rank candidates
        taste_vector = await self._taste_service.get_taste_vector(user_id)
        ranked = self._ranking_service.rank(
            deduplicated, taste_vector, intent.search_location
        )

        reasoning_steps.append(
            ReasoningStep(
                step="ranking",
                summary=f"Ranked {len(ranked)} candidates using taste model",
            )
        )

        # Step 7: Build response
        # Take top 3 (1 primary + up to 2 alternatives)
        top_candidates = ranked[:3]

        if not top_candidates:
            # No candidates available (empty state)
            empty_response = ConsultResponse(
                primary=PlaceResult(
                    place_name="No matches found",
                    address="",
                    reasoning="Try adjusting your search criteria",
                    source="discovered",
                    photos=[],
                ),
                alternatives=[],
                reasoning_steps=reasoning_steps,
            )
            await self._persist_consult_log(user_id, query, empty_response)
            return empty_response

        # Map candidates to PlaceResult
        primary_result = self._candidate_to_place_result(top_candidates[0])

        alternatives_results = [
            self._candidate_to_place_result(c) for c in top_candidates[1:3]
        ]

        reasoning_steps.append(
            ReasoningStep(
                step="response",
                summary=f"Selected {len(top_candidates)} final recommendations",
            )
        )

        response = ConsultResponse(
            primary=primary_result,
            alternatives=alternatives_results,
            reasoning_steps=reasoning_steps,
        )

        # Persist consult log (FR-010: write failures are logged, not propagated)
        await self._persist_consult_log(user_id, query, response)

        return response

    async def _persist_consult_log(
        self,
        user_id: str,
        query: str,
        response: ConsultResponse,
    ) -> None:
        """Attempt to persist a consult log record. Failures are logged, not raised."""
        try:
            from totoro_ai.db.models import ConsultLog

            log = ConsultLog(
                user_id=user_id,
                query=query,
                response=response.model_dump(),
                intent="consult",
            )
            await self._consult_log_repo.save(log)
        except Exception as exc:
            logger.warning(
                "Failed to persist consult log for user %s: %s", user_id, exc
            )

    @staticmethod
    def _candidate_to_place_result(candidate: Candidate) -> PlaceResult:
        """Convert Candidate to PlaceResult with deterministic reasoning."""
        reasoning_parts = []

        if candidate.source == "saved":
            reasoning_parts.append("Your saved place")
        else:
            reasoning_parts.append("Highly rated option")

        if candidate.distance and candidate.distance > 0:
            distance_km = candidate.distance / 1000
            reasoning_parts.append(f"{distance_km:.1f} km away")

        if candidate.popularity_score >= 0.8:
            reasoning_parts.append("very popular")
        elif candidate.popularity_score >= 0.6:
            reasoning_parts.append("popular")

        reasoning = (
            ", ".join(reasoning_parts) if reasoning_parts else "Recommended for you"
        )

        return PlaceResult(
            place_name=candidate.place_name,
            address=candidate.address,
            reasoning=reasoning,
            source=candidate.source,
            photos=[],
        )
