import math
from typing import Any

from totoro_ai.core.config import get_config
from totoro_ai.core.consult.types import Candidate
from totoro_ai.core.utils.geo import haversine_m

TASTE_DIMENSIONS = [
    "price_comfort",
    "dietary_alignment",
    "cuisine_frequency",
    "ambiance_preference",
    "crowd_tolerance",
    "cuisine_adventurousness",
    "time_of_day_preference",
    "distance_tolerance",
]


class RankingService:
    def __init__(self) -> None:
        self.config = get_config()

    def rank(
        self,
        candidates: list[Candidate],
        taste_vector: dict[str, float],
        search_location: dict[str, float] | None = None,
    ) -> list[Candidate]:
        """Rank candidates by multi-factor scoring.

        Args:
            candidates: List of Candidate objects to rank
            taste_vector: User taste model vector (8 dimensions)
            search_location: Reference location for distance scoring {'lat': float, 'lng': float}
                If None, distance weight is set to 0 and ranking uses taste, price, popularity.

        Returns:
            Candidates sorted by final_score descending, with _score fields added.
        """
        weights = self.config.ranking.weights

        scored = []
        for candidate in candidates:
            taste_sim = self._compute_taste_similarity(candidate, taste_vector)

            # Compute distance score if search_location is available
            if search_location and candidate.lat is not None and candidate.lng is not None:
                distance_m = haversine_m(
                    search_location["lat"],
                    search_location["lng"],
                    candidate.lat,
                    candidate.lng,
                )
                # Normalize distance to 0.0–1.0 score (far → 0, close → 1)
                # Use 10km as the inflection point
                distance_score = max(0.0, 1.0 - (distance_m / 10_000.0))
            else:
                # No location available, default to neutral 0.5
                distance_score = 0.5

            price_score = self._compute_price_score(candidate.price_range)
            popularity_score = candidate.popularity_score

            # Adjust weights if search_location is None
            if search_location is None:
                # Set distance weight to 0, re-normalize other weights
                distance_weight = 0.0
                taste_weight = weights.taste_similarity + weights.distance
                price_weight = weights.price_fit
                popularity_weight = weights.popularity
            else:
                distance_weight = weights.distance
                taste_weight = weights.taste_similarity
                price_weight = weights.price_fit
                popularity_weight = weights.popularity

            final_score = (
                taste_sim * taste_weight
                + distance_score * distance_weight
                + price_score * price_weight
                + popularity_score * popularity_weight
            )

            # Create a copy of the candidate with scores
            scored_candidate = candidate.model_copy(
                update={
                    "distance": distance_m
                    if (search_location and candidate.lat is not None and candidate.lng is not None)
                    else 0.0
                }
            )
            scored.append((scored_candidate, final_score))

        # Sort by final score descending
        return [c for c, _ in sorted(scored, key=lambda x: x[1], reverse=True)]

    def _compute_taste_similarity(
        self, candidate: Candidate, taste_vector: dict[str, float]
    ) -> float:
        """Compute taste vector similarity using weighted Euclidean distance."""
        observation = self._get_place_observation(candidate)
        ema = self.config.taste_model.ema

        weighted_sq_sum = sum(
            getattr(ema, dim)
            * (taste_vector.get(dim, 0.5) - observation.get(dim, 0.5)) ** 2
            for dim in TASTE_DIMENSIONS
        )

        distance = math.sqrt(weighted_sq_sum)
        return 1.0 / (1.0 + distance)

    def _compute_price_score(self, price_range: str | None) -> float:
        """Compute price fit score based on price range.

        For MVP, return neutral 0.5 for all ranges (deferred to Phase 4 for
        user preference matching).
        """
        return 0.5

    def _get_place_observation(self, candidate: Candidate) -> dict[str, float]:
        """Extract observation vector from candidate place."""
        observations = self.config.taste_model.observations

        return {
            "price_comfort": self._lookup_obs(
                observations.price_comfort, candidate.price_range
            ),
            "dietary_alignment": self._lookup_obs(
                observations.dietary_alignment, candidate.dietary_pref
            ),
            "cuisine_frequency": self._lookup_obs(
                observations.cuisine_frequency, candidate.cuisine_frequency
            ),
            "ambiance_preference": self._lookup_obs(
                observations.ambiance_preference, candidate.ambiance
            ),
            "crowd_tolerance": self._lookup_obs(
                observations.crowd_tolerance, candidate.crowd_level
            ),
            "cuisine_adventurousness": self._lookup_obs(
                observations.cuisine_adventurousness,
                candidate.cuisine_adventurousness,
            ),
            "time_of_day_preference": self._lookup_obs(
                observations.time_of_day_preference, candidate.time_of_day
            ),
            "distance_tolerance": self._lookup_obs(
                observations.distance_tolerance,
                self._distance_to_tolerance(candidate.distance),
            ),
        }

    def _distance_to_tolerance(self, distance_m: float) -> str | None:
        """Map distance in metres to tolerance value for lookup."""
        if distance_m == 0.0:
            return None  # Unknown distance, use default
        if distance_m < 500:
            return "very_close"
        if distance_m < 1000:
            return "nearby"
        if distance_m < 3000:
            return "moderate"
        return "far"

    def _lookup_obs(self, lookup_table: dict[str, float], key: str | None) -> float:
        if key is None or key not in lookup_table:
            return 0.5
        return lookup_table.get(key, 0.5)
