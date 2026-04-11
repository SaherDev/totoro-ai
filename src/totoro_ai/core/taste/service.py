from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.core.config import get_config
from totoro_ai.db.models import Place, SignalType
from totoro_ai.db.repositories import (
    PlaceRepository,
    SQLAlchemyPlaceRepository,
    SQLAlchemyTasteModelRepository,
)

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

DEFAULT_VECTOR = {dim: 0.5 for dim in TASTE_DIMENSIONS}


class TasteModelService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SQLAlchemyTasteModelRepository(session)
        self.place_repo: PlaceRepository = SQLAlchemyPlaceRepository(session)
        self.config = get_config()

    async def handle_place_saved(
        self,
        user_id: str,
        place_ids: list[str],
        place_metadata: dict[str, Any],
    ) -> None:
        gain = self.config.taste_model.signals.save
        for place_id in place_ids:
            await self.repository.log_interaction(
                user_id=user_id,
                signal_type=SignalType.SAVE,
                place_id=place_id,
                gain=gain,
                context={
                    "location": place_metadata.get("location"),
                    "time_of_day": place_metadata.get("time_of_day"),
                    "session_id": None,
                    "recommendation_id": None,
                },
            )
        await self._apply_taste_update(user_id, place_metadata, gain, is_positive=True)

    async def handle_recommendation_accepted(
        self,
        user_id: str,
        place_id: str,
    ) -> None:
        gain = self.config.taste_model.signals.accepted
        await self.repository.log_interaction(
            user_id=user_id,
            signal_type=SignalType.ACCEPTED,
            place_id=place_id,
            gain=gain,
            context={
                "location": None,
                "time_of_day": None,
                "session_id": None,
                "recommendation_id": None,
            },
        )
        place = await self.place_repo.get_by_id(place_id)
        await self._apply_taste_update(
            user_id, self._place_to_metadata(place), gain, is_positive=True
        )

    async def handle_recommendation_rejected(
        self,
        user_id: str,
        place_id: str,
    ) -> None:
        gain = self.config.taste_model.signals.rejected
        await self.repository.log_interaction(
            user_id=user_id,
            signal_type=SignalType.REJECTED,
            place_id=place_id,
            gain=gain,
            context={
                "location": None,
                "time_of_day": None,
                "session_id": None,
                "recommendation_id": None,
            },
        )
        place = await self.place_repo.get_by_id(place_id)
        await self._apply_taste_update(
            user_id, self._place_to_metadata(place), gain, is_positive=False
        )

    async def handle_onboarding_signal(
        self,
        user_id: str,
        place_id: str,
        confirmed: bool,
    ) -> None:
        gain = (
            self.config.taste_model.signals.onboarding_explicit_positive
            if confirmed
            else self.config.taste_model.signals.onboarding_explicit_negative
        )
        await self.repository.log_interaction(
            user_id=user_id,
            signal_type=SignalType.ONBOARDING_EXPLICIT,
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
        place = await self.place_repo.get_by_id(place_id)
        await self._apply_taste_update(
            user_id, self._place_to_metadata(place), gain, is_positive=confirmed
        )

    async def get_taste_vector(self, user_id: str) -> dict[str, float]:
        taste_model = await self.repository.get_by_user_id(user_id)

        if taste_model is None or taste_model.interaction_count == 0:
            return DEFAULT_VECTOR

        if taste_model.interaction_count < 10:
            return self._blend_vectors(
                personal=taste_model.parameters,
                defaults=DEFAULT_VECTOR,
                personal_weight=0.40,
            )

        return taste_model.parameters

    async def _apply_taste_update(
        self,
        user_id: str,
        place_metadata: dict[str, Any],
        gain: float,
        is_positive: bool,
    ) -> None:
        taste_model = await self.repository.get_by_user_id(user_id)
        current_vector = (
            taste_model.parameters.copy()
            if taste_model is not None
            else DEFAULT_VECTOR.copy()
        )

        new_vector = {}
        for dim in TASTE_DIMENSIONS:
            alpha = getattr(self.config.taste_model.ema, dim)
            v_current = current_vector.get(dim, 0.5)
            v_observation = self._get_observation_value(dim, place_metadata)

            if is_positive:
                alpha_gain = alpha * abs(gain)
                v_new = alpha_gain * v_observation + (1 - alpha_gain) * v_current
            else:
                alpha_gain = alpha * abs(gain)
                v_new = v_current - alpha_gain * (v_observation - v_current)

            new_vector[dim] = max(0.0, min(1.0, v_new))

        await self.repository.upsert(user_id=user_id, parameters=new_vector)
        await self.session.commit()

    def _place_to_metadata(self, place: Place | None) -> dict[str, Any]:
        if place is None:
            return {}
        hour = place.created_at.hour
        if 5 <= hour <= 10:
            time_of_day = "breakfast"
        elif 11 <= hour <= 14:
            time_of_day = "lunch"
        elif 15 <= hour <= 20:
            time_of_day = "dinner"
        else:
            time_of_day = "late_night"
        metadata: dict[str, Any] = {"time_of_day": time_of_day}
        if place.price_range is not None:
            metadata["price_range"] = place.price_range
        if place.ambiance is not None:
            metadata["ambiance"] = place.ambiance
        return metadata

    def _get_observation_value(
        self, dimension: str, place_metadata: dict[str, Any]
    ) -> float:
        observations = self.config.taste_model.observations
        dimension_obs = getattr(observations, dimension, None)

        if dimension_obs is None:
            return 0.5

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

        mapped_value = (
            dimension_obs.get(value) if isinstance(dimension_obs, dict) else None
        )
        return mapped_value if mapped_value is not None else 0.5

    def _blend_vectors(
        self,
        personal: dict[str, float],
        defaults: dict[str, float],
        personal_weight: float,
    ) -> dict[str, float]:
        default_weight = 1 - personal_weight
        return {
            dim: personal.get(dim, 0.5) * personal_weight
            + defaults.get(dim, 0.5) * default_weight
            for dim in TASTE_DIMENSIONS
        }
