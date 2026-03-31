import math
from typing import Any

from totoro_ai.core.config import get_config

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
        candidates: list[dict[str, Any]],
        taste_vector: dict[str, float],
    ) -> list[dict[str, Any]]:
        weights = self.config.ranking.weights

        scored = []
        for candidate in candidates:
            taste_sim = self._compute_taste_similarity(candidate, taste_vector)
            distance_score = max(0.0, min(1.0, candidate.get("distance_score", 0.5)))
            price_score = max(0.0, min(1.0, candidate.get("price_fit_score", 0.5)))
            popularity_score = max(
                0.0, min(1.0, candidate.get("popularity_score", 0.5))
            )

            final_score = (
                taste_sim * weights.taste_similarity
                + distance_score * weights.distance
                + price_score * weights.price_fit
                + popularity_score * weights.popularity
            )

            scored.append({**candidate, "final_score": final_score})

        return sorted(scored, key=lambda c: c["final_score"], reverse=True)

    def _compute_taste_similarity(
        self, candidate: dict[str, Any], taste_vector: dict[str, float]
    ) -> float:
        observation = self._get_place_observation(candidate)
        ema = self.config.taste_model.ema

        weighted_sq_sum = sum(
            getattr(ema, dim)
            * (taste_vector.get(dim, 0.5) - observation.get(dim, 0.5)) ** 2
            for dim in TASTE_DIMENSIONS
        )

        distance = math.sqrt(weighted_sq_sum)
        return 1.0 / (1.0 + distance)

    def _get_place_observation(self, candidate: dict[str, Any]) -> dict[str, float]:
        observations = self.config.taste_model.observations

        return {
            "price_comfort": self._lookup_obs(
                observations.price_comfort, candidate.get("price_range")
            ),
            "dietary_alignment": self._lookup_obs(
                observations.dietary_alignment, candidate.get("dietary_pref")
            ),
            "cuisine_frequency": self._lookup_obs(
                observations.cuisine_frequency, candidate.get("cuisine_frequency")
            ),
            "ambiance_preference": self._lookup_obs(
                observations.ambiance_preference, candidate.get("ambiance")
            ),
            "crowd_tolerance": self._lookup_obs(
                observations.crowd_tolerance, candidate.get("crowd_level")
            ),
            "cuisine_adventurousness": self._lookup_obs(
                observations.cuisine_adventurousness,
                candidate.get("cuisine_adventurousness"),
            ),
            "time_of_day_preference": self._lookup_obs(
                observations.time_of_day_preference, candidate.get("time_of_day")
            ),
            "distance_tolerance": self._lookup_obs(
                observations.distance_tolerance, candidate.get("distance")
            ),
        }

    def _lookup_obs(self, lookup_table: dict[str, float], key: str | None) -> float:
        if key is None or key not in lookup_table:
            return 0.5
        return lookup_table.get(key, 0.5)
