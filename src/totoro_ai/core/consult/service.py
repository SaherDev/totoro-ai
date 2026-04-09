"""Consult service — 6-step place recommendation pipeline (ADR-049, ADR-050)."""

from __future__ import annotations

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


class ConsultService:
    """6-step place recommendation pipeline.

    Phases:
    1. Parse intent from query
    2. Retrieve saved places matching query
    3. Discover external candidates via Places API
    4. Validate saved candidates (conditional)
    5. Rank all candidates
    6. Build response with top 3 + reasoning steps
    """

    def __init__(
        self,
        intent_parser: IntentParser,
        recall_service: RecallService,
        places_client: PlacesClient,
        taste_service: TasteModelService,
        ranking_service: RankingService,
    ) -> None:
        """Initialize ConsultService with 5 dependencies (ADR-019)."""
        self._intent_parser = intent_parser
        self._recall_service = recall_service
        self._places_client = places_client
        self._taste_service = taste_service
        self._ranking_service = ranking_service

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
        # Step 1: Parse intent from query
        search_location_dict = {"lat": location.lat, "lng": location.lng} if location else None
        intent = await self._intent_parser.parse(query, location=search_location_dict)

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
            mapper = RecallResultToCandidateMapper()
            for recall_result in recall_results.results:
                candidate = mapper.map(recall_result)

                # Apply intent filters (cuisine, price_range, radius)
                if intent.cuisine and candidate.cuisine:
                    # Simple substring matching for MVP
                    if intent.cuisine.lower() not in candidate.cuisine.lower():
                        continue
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

                mapper = ExternalCandidateMapper()
                for google_result in discovery_results:
                    candidate = mapper.map(google_result)

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
            except RuntimeError as e:
                # External provider failure: graceful fallback to saved candidates only
                reasoning_steps.append(
                    ReasoningStep(
                        step="discovery",
                        summary=f"External discovery skipped (provider unavailable)",
                    )
                )
        else:
            reasoning_steps.append(
                ReasoningStep(
                    step="discovery",
                    summary="Discovery skipped (no location context)",
                )
            )

        # Step 4: Deduplication by place_id (saved entry wins)
        all_candidates = saved_candidates + discovered_candidates
        seen_ids = set()
        deduplicated: list[Candidate] = []

        for candidate in all_candidates:
            if candidate.place_id not in seen_ids:
                deduplicated.append(candidate)
                seen_ids.add(candidate.place_id)

        # Step 5: Conditional validation of saved candidates
        if intent.validate_candidates and saved_candidates:
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
                c for c in deduplicated if c.source == "discovered" or c in valid_candidates
            ]
        else:
            reasoning_steps.append(
                ReasoningStep(
                    step="validation",
                    summary="Validation skipped (no live constraints)",
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
            return ConsultResponse(
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

        return ConsultResponse(
            primary=primary_result,
            alternatives=alternatives_results,
            reasoning_steps=reasoning_steps,
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

        reasoning = ", ".join(reasoning_parts) if reasoning_parts else "Recommended for you"

        return PlaceResult(
            place_name=candidate.place_name,
            address=candidate.address,
            reasoning=reasoning,
            source=candidate.source,
            photos=[],
        )
