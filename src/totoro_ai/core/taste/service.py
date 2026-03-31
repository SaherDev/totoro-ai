"""TasteModelService - core taste model updates and personalization routing"""

import math
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.core.config import get_config
from totoro_ai.db.models import SignalType
from totoro_ai.db.repositories import SQLAlchemyTasteModelRepository


class TasteModelService:
    """Service for taste model updates via EMA and personalization routing"""

    # 8 taste dimensions (must match config and TasteModel.parameters JSONB keys)
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

    # Default vector for zero-interaction users
    DEFAULT_VECTOR = {dim: 0.5 for dim in TASTE_DIMENSIONS}

    def __init__(self, session: AsyncSession):
        """Initialize service with database session

        Args:
            session: AsyncSession for database operations
        """
        self.session = session
        self.repository = SQLAlchemyTasteModelRepository(session)
        self.config = get_config()

    async def handle_place_saved(
        self,
        user_id: str,
        place_id: str,
        place_metadata: dict[str, Any],
    ) -> None:
        """Handle place saved signal

        Args:
            user_id: User identifier
            place_id: Place identifier
            place_metadata: Place attributes for v_observation mapping
        """
        signal_type = SignalType.SAVE
        gain = self.config.taste_model.signals.save

        # Log interaction first (strict consistency: must succeed before cache update)
        await self.repository.log_interaction(
            user_id=user_id,
            signal_type=signal_type,
            place_id=place_id,
            gain=gain,
            context={
                "location": place_metadata.get("location"),
                "time_of_day": place_metadata.get("time_of_day"),
                "session_id": None,
                "recommendation_id": None,
            },
        )

        # Update taste model cache
        await self._apply_taste_update(user_id, place_metadata, gain, is_positive=True)

    async def handle_recommendation_accepted(
        self,
        user_id: str,
        place_id: str,
    ) -> None:
        """Handle recommendation accepted signal

        Args:
            user_id: User identifier
            place_id: Place identifier
        """
        signal_type = SignalType.ACCEPTED
        gain = self.config.taste_model.signals.accepted

        # Log interaction first
        await self.repository.log_interaction(
            user_id=user_id,
            signal_type=signal_type,
            place_id=place_id,
            gain=gain,
            context={
                "location": None,
                "time_of_day": None,
                "session_id": None,
                "recommendation_id": None,
            },
        )

        # Update taste model cache
        # Note: We'd need the place_metadata here, but for now accept generic update
        await self._increment_and_update_confidence(user_id)

    async def handle_recommendation_rejected(
        self,
        user_id: str,
        place_id: str,
    ) -> None:
        """Handle recommendation rejected signal

        Args:
            user_id: User identifier
            place_id: Place identifier
        """
        signal_type = SignalType.REJECTED
        gain = self.config.taste_model.signals.rejected

        # Log interaction first
        await self.repository.log_interaction(
            user_id=user_id,
            signal_type=signal_type,
            place_id=place_id,
            gain=gain,
            context={
                "location": None,
                "time_of_day": None,
                "session_id": None,
                "recommendation_id": None,
            },
        )

        # Update taste model cache
        await self._increment_and_update_confidence(user_id)

    async def handle_onboarding_signal(
        self,
        user_id: str,
        place_id: str,
        confirmed: bool,
    ) -> None:
        """Handle onboarding taste chip signal

        Args:
            user_id: User identifier
            place_id: Place identifier (of the taste chip)
            confirmed: True if confirmed, False if dismissed
        """
        signal_type = SignalType.ONBOARDING_EXPLICIT
        gain = (
            self.config.taste_model.signals.onboarding_explicit_positive
            if confirmed
            else self.config.taste_model.signals.onboarding_explicit_negative
        )

        # Log interaction first
        await self.repository.log_interaction(
            user_id=user_id,
            signal_type=signal_type,
            place_id=place_id,
            gain=gain,
            context={
                "location": None,
                "time_of_day": None,
                "session_id": None,
                "recommendation_id": None,
                "confirmed": confirmed,
            },
        )

        # Update taste model cache
        await self._increment_and_update_confidence(user_id)

    async def get_taste_vector(self, user_id: str) -> dict[str, float]:
        """Retrieve personalized taste vector with routing logic

        Routing logic:
        - 0 interactions: all-0.5 defaults (cold start)
        - 1–9 interactions: 40% stored vector + 60% defaults (low-confidence blend)
        - ≥10 interactions: stored vector (high confidence personalization)

        Args:
            user_id: User identifier

        Returns:
            8-dimension taste vector {dimension: float [0, 1]}
        """
        taste_model = await self.repository.get_by_user_id(user_id)

        # No record yet (zero interactions)
        if taste_model is None:
            return self.DEFAULT_VECTOR

        # Route based on interaction count
        if taste_model.interaction_count == 0:
            return self.DEFAULT_VECTOR
        elif taste_model.interaction_count < 10:
            # Low-confidence blend: 40% personal, 60% defaults
            return self._blend_vectors(
                personal=taste_model.parameters,
                defaults=self.DEFAULT_VECTOR,
                personal_weight=0.40,
            )
        else:
            # High-confidence: return stored vector
            return taste_model.parameters

    async def _apply_taste_update(
        self,
        user_id: str,
        place_metadata: dict[str, Any],
        gain: float,
        is_positive: bool,
    ) -> None:
        """Apply EMA update to taste model

        Args:
            user_id: User identifier
            place_metadata: Place attributes for v_observation
            gain: Signal gain/weight from config
            is_positive: True for positive signals (save, accepted), False for negative (rejected)
        """
        # Get current taste model or create default
        taste_model = await self.repository.get_by_user_id(user_id)
        if taste_model is None:
            current_vector = self.DEFAULT_VECTOR.copy()
            interaction_count = 0
        else:
            current_vector = taste_model.parameters.copy()
            interaction_count = taste_model.interaction_count

        # Apply EMA update for each dimension
        new_vector = {}
        for dim in self.TASTE_DIMENSIONS:
            alpha = getattr(self.config.taste_model.ema, dim)
            v_current = current_vector.get(dim, 0.5)
            v_observation = self._get_observation_value(dim, place_metadata)
            v_prior = v_current

            if is_positive:
                # Positive formula: v_new = α × |gain| × v_obs + (1 − α × |gain|) × v_current
                alpha_gain = alpha * abs(gain)
                v_new = alpha_gain * v_observation + (1 - alpha_gain) * v_current
            else:
                # Negative formula: v_new = v_current − α × |gain| × (v_obs − v_prior)
                alpha_gain = alpha * abs(gain)
                v_new = v_current - alpha_gain * (v_observation - v_prior)

            # Clamp to [0, 1]
            v_new = max(0.0, min(1.0, v_new))
            new_vector[dim] = v_new

        # Increment interaction count and recompute confidence
        new_interaction_count = interaction_count + 1
        new_confidence = 1 - math.exp(-new_interaction_count / 10)

        # Upsert taste model
        await self.repository.upsert(
            user_id=user_id,
            parameters=new_vector,
            confidence=new_confidence,
            interaction_count=new_interaction_count,
        )

        # Commit transaction
        await self.session.commit()

    async def _increment_and_update_confidence(self, user_id: str) -> None:
        """Increment interaction count and recompute confidence

        Called when we don't have place metadata for EMA update.
        """
        taste_model = await self.repository.get_by_user_id(user_id)
        if taste_model is None:
            current_vector = self.DEFAULT_VECTOR.copy()
            interaction_count = 0
        else:
            current_vector = taste_model.parameters.copy()
            interaction_count = taste_model.interaction_count

        # Increment and recompute confidence
        new_interaction_count = interaction_count + 1
        new_confidence = 1 - math.exp(-new_interaction_count / 10)

        # Upsert (keep current vector)
        await self.repository.upsert(
            user_id=user_id,
            parameters=current_vector,
            confidence=new_confidence,
            interaction_count=new_interaction_count,
        )

        # Commit transaction
        await self.session.commit()

    def _get_observation_value(self, dimension: str, place_metadata: dict[str, Any]) -> float:
        """Get v_observation for a dimension from place metadata

        Maps place attributes to observation values via config lookup table.
        If metadata doesn't have the field, defaults to 0.5 (neutral).

        Args:
            dimension: Taste dimension name
            place_metadata: Place attributes

        Returns:
            v_observation value [0, 1]
        """
        observations = self.config.taste_model.observations
        dimension_obs = getattr(observations, dimension, None)

        if dimension_obs is None:
            return 0.5

        # Get place attribute for this dimension
        if dimension == "price_comfort":
            value = place_metadata.get("price_range")
        elif dimension == "dietary_alignment":
            value = place_metadata.get("dietary_pref")
        elif dimension == "cuisine_frequency":
            value = place_metadata.get("cuisine_frequency")
        elif dimension == "ambiance_preference":
            value = place_metadata.get("ambiance")
        elif dimension == "crowd_tolerance":
            value = place_metadata.get("crowd_level")
        elif dimension == "cuisine_adventurousness":
            value = place_metadata.get("cuisine_adventurousness")
        elif dimension == "time_of_day_preference":
            value = place_metadata.get("time_of_day")
        elif dimension == "distance_tolerance":
            value = place_metadata.get("distance")
        else:
            value = None

        if value is None:
            return 0.5

        # Look up mapped value
        mapped_value = dimension_obs.get(value) if isinstance(dimension_obs, dict) else None
        return mapped_value if mapped_value is not None else 0.5

    def _blend_vectors(
        self,
        personal: dict[str, float],
        defaults: dict[str, float],
        personal_weight: float,
    ) -> dict[str, float]:
        """Blend two taste vectors by weight

        Args:
            personal: User's stored taste vector
            defaults: Default vector
            personal_weight: Weight for personal vector [0, 1]

        Returns:
            Blended vector
        """
        default_weight = 1 - personal_weight
        return {
            dim: personal.get(dim, 0.5) * personal_weight + defaults.get(dim, 0.5) * default_weight
            for dim in self.TASTE_DIMENSIONS
        }
