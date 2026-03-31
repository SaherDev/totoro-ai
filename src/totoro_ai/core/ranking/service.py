"""RankingService - multi-factor candidate ranking with taste personalization"""

from typing import Any

from totoro_ai.core.config import get_config


class RankingService:
    """Score and rank place candidates using weighted multi-factor scoring"""

    def __init__(self) -> None:
        """Initialize ranking service with config"""
        self.config = get_config()

    def rank(
        self,
        candidates: list[dict[str, Any]],
        taste_vector: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Rank candidates using weighted multi-factor scoring.

        Scoring formula:
            final_score = (
                taste_similarity × w_taste +
                distance_score × w_distance +
                price_fit_score × w_price +
                popularity_score × w_popularity
            )

        All weights read from config/app.yaml ranking.weights (no hardcoded floats).

        Args:
            candidates: List of place dicts with score metadata
            taste_vector: User's 8-dimension taste vector [0, 1]

        Returns:
            Candidates sorted descending by final_score
        """
        weights = self.config.ranking.weights

        # Score each candidate
        scored = []
        for candidate in candidates:
            # Compute taste similarity (dot product of taste vector and observation)
            taste_sim = self._compute_taste_similarity(candidate, taste_vector)

            # Get or compute other scores from candidate metadata
            distance_score = candidate.get("distance_score", 0.5)
            price_score = candidate.get("price_fit_score", 0.5)
            popularity_score = candidate.get("popularity_score", 0.5)

            # Clamp all scores to [0, 1]
            taste_sim = max(0.0, min(1.0, taste_sim))
            distance_score = max(0.0, min(1.0, distance_score))
            price_score = max(0.0, min(1.0, price_score))
            popularity_score = max(0.0, min(1.0, popularity_score))

            # Weighted sum
            final_score = (
                taste_sim * weights.taste_similarity
                + distance_score * weights.distance
                + price_score * weights.price_fit
                + popularity_score * weights.popularity
            )

            scored.append({**candidate, "final_score": final_score})

        # Sort by final_score descending
        return sorted(scored, key=lambda c: c["final_score"], reverse=True)

    def _compute_taste_similarity(
        self, candidate: dict[str, Any], taste_vector: dict[str, float]
    ) -> float:
        """Compute taste similarity between candidate place and user's taste vector.

        Maps place metadata to observation vector, then computes dot-product similarity.

        Args:
            candidate: Place dict with metadata (cuisine, price_range, etc.)
            taste_vector: User's 8-dimension taste vector

        Returns:
            Similarity score [0, 1]
        """
        # Map candidate metadata to observation values per dimension
        observation = self._get_place_observation(candidate)

        # Dot product: sum(taste[i] * observation[i]) for all 8 dimensions
        dimensions = [
            "price_comfort",
            "dietary_alignment",
            "cuisine_frequency",
            "ambiance_preference",
            "crowd_tolerance",
            "cuisine_adventurousness",
            "time_of_day_preference",
            "distance_tolerance",
        ]

        similarity = sum(
            taste_vector.get(dim, 0.5) * observation.get(dim, 0.5)
            for dim in dimensions
        )

        # Normalize to [0, 1] (max possible is 8 if all are 1.0)
        return min(1.0, similarity / 8.0)

    def _get_place_observation(self, candidate: dict[str, Any]) -> dict[str, float]:
        """Map place metadata to observation values.

        Uses config lookup tables to map place attributes to v_observation values.
        Defaults to 0.5 (neutral) for missing fields.

        Args:
            candidate: Place dict with fields (cuisine, price_range, etc.)

        Returns:
            Observation vector {dimension: float [0, 1]}
        """
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
                observations.cuisine_adventurousness, candidate.get("cuisine_adventurousness")
            ),
            "time_of_day_preference": self._lookup_obs(
                observations.time_of_day_preference, candidate.get("time_of_day")
            ),
            "distance_tolerance": self._lookup_obs(
                observations.distance_tolerance, candidate.get("distance")
            ),
        }

    def _lookup_obs(self, lookup_table: dict[str, float], key: str | None) -> float:
        """Look up observation value in config table.

        Args:
            lookup_table: Dict mapping keys to float values
            key: Key to look up (e.g., "low", "mid", "high" for price_range)

        Returns:
            Mapped value [0, 1] or 0.5 (neutral) if not found
        """
        if key is None or key not in lookup_table:
            return 0.5
        return lookup_table.get(key, 0.5)
