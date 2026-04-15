"""Ranking service — multi-factor scoring over PlaceObject (feature 019).

The ranker consumes `PlaceObject`s flowing out of recall/enrichment and
returns `ScoredPlace` wrappers in descending score order. Scoring signals
are read from `PlaceObject.attributes.*` (cuisine, price_hint, ambiance,
dietary, good_for), Tier-2 `lat`/`lng` (populated only after
`enrich_batch`), and `popularity` (Tier 3). Missing tier data degrades
gracefully: absent coordinates → neutral distance score; absent popularity
→ neutral popularity; absent attribute value → taste dimension falls back
to 0.5.
"""

from __future__ import annotations

import math

from totoro_ai.core.config import get_config
from totoro_ai.core.consult.types import ScoredPlace
from totoro_ai.core.places.models import PlaceObject
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
        places: list[PlaceObject],
        taste_vector: dict[str, float],
        search_location: dict[str, float] | None = None,
        sources_by_place_id: dict[str, str] | None = None,
    ) -> list[ScoredPlace]:
        """Rank `PlaceObject`s by multi-factor scoring.

        Args:
            places: candidates flowing out of recall/discovery.
            taste_vector: the user's 8-dim taste model vector.
            search_location: reference point for distance scoring, or None.
            sources_by_place_id: optional mapping from `place_id` to the
                logical source ("saved" or "discovered"). Used to apply
                the saved-source boost. When omitted, every place is
                treated as "saved" (the saved-source boost applies).

        Returns:
            A list of `ScoredPlace` sorted by `score` descending. One
            entry per input place; input order is not preserved.
        """
        weights = self.config.ranking.weights
        sources_by_place_id = sources_by_place_id or {}

        scored: list[ScoredPlace] = []
        for place in places:
            source = sources_by_place_id.get(place.place_id, "saved")

            taste_sim, distance_m = self._taste_and_distance(
                place, taste_vector, search_location
            )
            distance_score = self._distance_score(distance_m, search_location)

            price_score = self._compute_price_score(place.attributes.price_hint)
            popularity_score = place.popularity if place.popularity is not None else 0.5

            if search_location is None:
                distance_weight = 0.0
                taste_weight = weights.taste_similarity + weights.distance
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
            if source == "saved":
                final_score = min(1.0, final_score + weights.source_boost)

            scored.append(
                ScoredPlace(
                    place=place,
                    score=final_score,
                    distance_m=distance_m,
                    source=source,
                )
            )

        scored.sort(key=lambda sp: sp.score, reverse=True)
        return scored

    # ------------------------------------------------------------------
    # Scoring internals
    # ------------------------------------------------------------------
    def _taste_and_distance(
        self,
        place: PlaceObject,
        taste_vector: dict[str, float],
        search_location: dict[str, float] | None,
    ) -> tuple[float, float]:
        distance_m = 0.0
        if (
            search_location is not None
            and place.lat is not None
            and place.lng is not None
        ):
            distance_m = haversine_m(
                search_location["lat"], search_location["lng"], place.lat, place.lng
            )

        observation = self._get_place_observation(place, distance_m)
        ema = self.config.taste_model.ema
        weighted_sq_sum = sum(
            getattr(ema, dim)
            * (taste_vector.get(dim, 0.5) - observation.get(dim, 0.5)) ** 2
            for dim in TASTE_DIMENSIONS
        )
        distance = math.sqrt(weighted_sq_sum)
        return 1.0 / (1.0 + distance), distance_m

    @staticmethod
    def _distance_score(
        distance_m: float, search_location: dict[str, float] | None
    ) -> float:
        if search_location is None:
            return 0.5
        if distance_m == 0.0:
            return 0.5
        return max(0.0, 1.0 - (distance_m / 10_000.0))

    @staticmethod
    def _compute_price_score(price_hint: str | None) -> float:
        """Neutral price fit until user-preference matching lands."""
        del price_hint
        return 0.5

    def _get_place_observation(
        self, place: PlaceObject, distance_m: float
    ) -> dict[str, float]:
        observations = self.config.taste_model.observations
        first_dietary = (
            place.attributes.dietary[0] if place.attributes.dietary else None
        )
        first_good_for = (
            place.attributes.good_for[0] if place.attributes.good_for else None
        )
        return {
            "price_comfort": self._lookup_obs(
                observations.price_comfort, place.attributes.price_hint
            ),
            "dietary_alignment": self._lookup_obs(
                observations.dietary_alignment, first_dietary
            ),
            "cuisine_frequency": self._lookup_obs(
                observations.cuisine_frequency, place.attributes.cuisine
            ),
            "ambiance_preference": self._lookup_obs(
                observations.ambiance_preference, place.attributes.ambiance
            ),
            "crowd_tolerance": self._lookup_obs(
                observations.crowd_tolerance, first_good_for
            ),
            "cuisine_adventurousness": self._lookup_obs(
                observations.cuisine_adventurousness, place.attributes.cuisine
            ),
            "time_of_day_preference": self._lookup_obs(
                observations.time_of_day_preference, first_good_for
            ),
            "distance_tolerance": self._lookup_obs(
                observations.distance_tolerance,
                self._distance_to_tolerance(distance_m),
            ),
        }

    @staticmethod
    def _distance_to_tolerance(distance_m: float) -> str | None:
        if distance_m == 0.0:
            return None
        if distance_m < 500:
            return "very_close"
        if distance_m < 1000:
            return "nearby"
        if distance_m < 3000:
            return "moderate"
        return "far"

    @staticmethod
    def _lookup_obs(lookup_table: dict[str, float], key: str | None) -> float:
        if key is None or key not in lookup_table:
            return 0.5
        return lookup_table.get(key, 0.5)
