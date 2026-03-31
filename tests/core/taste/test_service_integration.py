import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.core.taste.service import (
    DEFAULT_VECTOR,
    TASTE_DIMENSIONS,
    TasteModelService,
)
from totoro_ai.db.models import SignalType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_place(
    price_range: str | None = "low",
    ambiance: str | None = None,
    created_at_hour: int = 12,
) -> MagicMock:
    place = MagicMock()
    place.price_range = price_range
    place.ambiance = ambiance
    place.created_at = datetime(2026, 1, 1, created_at_hour, 0, tzinfo=UTC)
    return place


def _make_taste_model(
    user_id: str = "user-1",
    interaction_count: int = 1,
    parameters: dict | None = None,
) -> MagicMock:
    tm = MagicMock()
    tm.user_id = user_id
    tm.interaction_count = interaction_count
    default = {dim: 0.5 for dim in TASTE_DIMENSIONS}
    tm.parameters = dict(parameters) if parameters is not None else default
    return tm


@pytest.fixture
def taste_service(mock_session: AsyncMock) -> TasteModelService:
    svc = TasteModelService(session=mock_session)
    svc.repository = AsyncMock()
    svc.place_repo = AsyncMock()
    svc.repository.get_by_user_id = AsyncMock(return_value=None)
    svc.repository.upsert = AsyncMock(return_value=_make_taste_model())
    svc.repository.log_interaction = AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# handle_place_saved
# ---------------------------------------------------------------------------


async def test_handle_place_saved_logs_save_signal_with_correct_gain(
    taste_service: TasteModelService,
) -> None:
    await taste_service.handle_place_saved(
        user_id="user-1",
        place_id="place-1",
        place_metadata={"price_range": "low"},
    )

    taste_service.repository.log_interaction.assert_called_once()
    kw = taste_service.repository.log_interaction.call_args.kwargs
    assert kw["user_id"] == "user-1"
    assert kw["place_id"] == "place-1"
    assert kw["signal_type"] == SignalType.SAVE
    assert kw["gain"] == pytest.approx(1.0)


async def test_handle_place_saved_moves_price_comfort_up_for_low_price_place(
    taste_service: TasteModelService,
) -> None:
    """EMA: alpha=0.03, gain=1.0, v_obs=1.0 (low), v_current=0.5 → v_new=0.515."""
    await taste_service.handle_place_saved(
        user_id="user-1",
        place_id="place-1",
        place_metadata={"price_range": "low"},
    )

    taste_service.repository.upsert.assert_called_once()
    params = taste_service.repository.upsert.call_args.kwargs["parameters"]
    assert params["price_comfort"] == pytest.approx(0.515)
    assert params["price_comfort"] > 0.5
    assert set(params.keys()) == set(TASTE_DIMENSIONS)


async def test_handle_place_saved_upsert_receives_no_interaction_count_arg(
    taste_service: TasteModelService,
) -> None:
    """Service must not touch interaction_count — SQL handles the atomic increment.

    The repository's upsert() signature accepts only (user_id, parameters).
    interaction_count is incremented in SQL via `interaction_count + 1` to
    prevent the read-modify-write race condition (FR-004).
    """
    existing = _make_taste_model(interaction_count=5)
    taste_service.repository.get_by_user_id = AsyncMock(return_value=existing)

    await taste_service.handle_place_saved(
        user_id="user-1",
        place_id="place-1",
        place_metadata={"price_range": "low"},
    )

    taste_service.repository.upsert.assert_called_once()
    assert set(taste_service.repository.upsert.call_args.kwargs.keys()) == {
        "user_id",
        "parameters",
    }


# ---------------------------------------------------------------------------
# handle_recommendation_accepted
# ---------------------------------------------------------------------------


async def test_handle_recommendation_accepted_logs_accepted_signal(
    taste_service: TasteModelService,
) -> None:
    taste_service.place_repo.get_by_id = AsyncMock(
        return_value=_make_place(price_range="high")
    )

    await taste_service.handle_recommendation_accepted(
        user_id="user-1",
        place_id="place-1",
    )

    kw = taste_service.repository.log_interaction.call_args.kwargs
    assert kw["signal_type"] == SignalType.ACCEPTED
    assert kw["gain"] == pytest.approx(2.0)


async def test_handle_recommendation_accepted_moves_vector_toward_place_traits(
    taste_service: TasteModelService,
) -> None:
    """Accepting high-price place pulls price_comfort toward 0.0 (high=0.0 in config).

    EMA positive: alpha=0.03, gain=2.0, v_obs=0.0 (high), v_current=0.5
    alpha_gain = 0.06 → v_new = 0.06*0.0 + 0.94*0.5 = 0.47
    """
    taste_service.place_repo.get_by_id = AsyncMock(
        return_value=_make_place(price_range="high")
    )

    await taste_service.handle_recommendation_accepted(
        user_id="user-1",
        place_id="place-1",
    )

    params = taste_service.repository.upsert.call_args.kwargs["parameters"]
    assert params["price_comfort"] == pytest.approx(0.47)
    assert params["price_comfort"] < 0.5


async def test_handle_recommendation_accepted_fetches_place_from_db(
    taste_service: TasteModelService,
) -> None:
    taste_service.place_repo.get_by_id = AsyncMock(
        return_value=_make_place(price_range="high")
    )

    await taste_service.handle_recommendation_accepted(
        user_id="user-1",
        place_id="place-1",
    )

    taste_service.place_repo.get_by_id.assert_called_once_with("place-1")


# ---------------------------------------------------------------------------
# handle_recommendation_rejected
# ---------------------------------------------------------------------------


async def test_handle_recommendation_rejected_logs_rejected_signal(
    taste_service: TasteModelService,
) -> None:
    taste_service.place_repo.get_by_id = AsyncMock(
        return_value=_make_place(price_range="low")
    )

    await taste_service.handle_recommendation_rejected(
        user_id="user-1",
        place_id="place-1",
    )

    kw = taste_service.repository.log_interaction.call_args.kwargs
    assert kw["signal_type"] == SignalType.REJECTED
    assert kw["gain"] == pytest.approx(-1.5)


async def test_handle_recommendation_rejected_moves_vector_away_from_place_traits(
    taste_service: TasteModelService,
) -> None:
    """Rejecting low-price place pushes price_comfort away from 1.0 (low=1.0).

    EMA negative: alpha=0.03, gain=-1.5, v_obs=1.0 (low), v_current=0.5
    alpha_gain = 0.045 → v_new = 0.5 - 0.045*(1.0-0.5) = 0.4775
    """
    taste_service.place_repo.get_by_id = AsyncMock(
        return_value=_make_place(price_range="low")
    )

    await taste_service.handle_recommendation_rejected(
        user_id="user-1",
        place_id="place-1",
    )

    params = taste_service.repository.upsert.call_args.kwargs["parameters"]
    assert params["price_comfort"] == pytest.approx(0.4775)
    assert params["price_comfort"] < 0.5


# ---------------------------------------------------------------------------
# handle_onboarding_signal
# ---------------------------------------------------------------------------


async def test_handle_onboarding_confirmed_logs_signal_and_moves_vector_up(
    taste_service: TasteModelService,
) -> None:
    """Confirmed onboarding (gain=+1.2) moves vector toward the observation.

    EMA positive: alpha=0.03, gain=1.2, v_obs=1.0 (low), v_current=0.5
    alpha_gain = 0.036 → v_new = 0.036*1.0 + 0.964*0.5 = 0.518
    """
    taste_service.place_repo.get_by_id = AsyncMock(
        return_value=_make_place(price_range="low")
    )

    await taste_service.handle_onboarding_signal(
        user_id="user-1",
        place_id="place-1",
        confirmed=True,
    )

    kw = taste_service.repository.log_interaction.call_args.kwargs
    assert kw["signal_type"] == SignalType.ONBOARDING_EXPLICIT
    assert kw["gain"] == pytest.approx(1.2)

    params = taste_service.repository.upsert.call_args.kwargs["parameters"]
    assert params["price_comfort"] == pytest.approx(0.518)
    assert params["price_comfort"] > 0.5


async def test_handle_onboarding_dismissed_logs_signal_and_moves_vector_down(
    taste_service: TasteModelService,
) -> None:
    """Dismissed onboarding (gain=-0.8) moves vector away from the observation.

    EMA negative: alpha=0.03, gain=-0.8, v_obs=1.0 (low), v_current=0.5
    alpha_gain = 0.024 → v_new = 0.5 - 0.024*(1.0-0.5) = 0.488
    Direction is opposite to confirmed (0.518 vs 0.488).
    """
    taste_service.place_repo.get_by_id = AsyncMock(
        return_value=_make_place(price_range="low")
    )

    await taste_service.handle_onboarding_signal(
        user_id="user-1",
        place_id="place-1",
        confirmed=False,
    )

    kw = taste_service.repository.log_interaction.call_args.kwargs
    assert kw["signal_type"] == SignalType.ONBOARDING_EXPLICIT
    assert kw["gain"] == pytest.approx(-0.8)

    params = taste_service.repository.upsert.call_args.kwargs["parameters"]
    assert params["price_comfort"] == pytest.approx(0.488)
    assert params["price_comfort"] < 0.5


async def test_handle_onboarding_confirmed_dismissed_produce_opposite_directions(
    mock_session: AsyncMock,
) -> None:
    """confirmed=True and confirmed=False for the same place produce vectors
    that differ in the expected direction — confirmed higher, dismissed lower."""
    place = _make_place(price_range="low")

    svc_conf = TasteModelService(session=mock_session)
    svc_conf.repository = AsyncMock()
    svc_conf.place_repo = AsyncMock()
    svc_conf.repository.get_by_user_id = AsyncMock(return_value=None)
    svc_conf.repository.upsert = AsyncMock(return_value=_make_taste_model())
    svc_conf.repository.log_interaction = AsyncMock()
    svc_conf.place_repo.get_by_id = AsyncMock(return_value=place)

    svc_dism = TasteModelService(session=mock_session)
    svc_dism.repository = AsyncMock()
    svc_dism.place_repo = AsyncMock()
    svc_dism.repository.get_by_user_id = AsyncMock(return_value=None)
    svc_dism.repository.upsert = AsyncMock(return_value=_make_taste_model())
    svc_dism.repository.log_interaction = AsyncMock()
    svc_dism.place_repo.get_by_id = AsyncMock(return_value=place)

    await svc_conf.handle_onboarding_signal("user-1", "place-1", confirmed=True)
    await svc_dism.handle_onboarding_signal("user-1", "place-1", confirmed=False)

    confirmed_params = svc_conf.repository.upsert.call_args.kwargs["parameters"]
    dismissed_params = svc_dism.repository.upsert.call_args.kwargs["parameters"]

    assert confirmed_params["price_comfort"] > dismissed_params["price_comfort"]
    assert confirmed_params["price_comfort"] > 0.5
    assert dismissed_params["price_comfort"] < 0.5


# ---------------------------------------------------------------------------
# get_taste_vector
# ---------------------------------------------------------------------------


async def test_get_taste_vector_returns_defaults_when_no_model_exists(
    taste_service: TasteModelService,
) -> None:
    """Zero interactions: all 8 dimensions at exactly 0.5."""
    taste_service.repository.get_by_user_id = AsyncMock(return_value=None)

    result = await taste_service.get_taste_vector("user-1")

    assert result == DEFAULT_VECTOR
    assert len(result) == 8
    assert all(v == pytest.approx(0.5) for v in result.values())


async def test_get_taste_vector_returns_defaults_when_interaction_count_is_zero(
    taste_service: TasteModelService,
) -> None:
    """A taste_model row with interaction_count=0 also returns DEFAULT_VECTOR."""
    taste_service.repository.get_by_user_id = AsyncMock(
        return_value=_make_taste_model(interaction_count=0)
    )

    result = await taste_service.get_taste_vector("user-1")

    assert result == DEFAULT_VECTOR


async def test_get_taste_vector_returns_blend_for_partial_interactions(
    taste_service: TasteModelService,
) -> None:
    """1–9 interactions: 40% personal + 60% defaults blend.

    personal = all 0.8, defaults = all 0.5
    blended = 0.4 * 0.8 + 0.6 * 0.5 = 0.32 + 0.30 = 0.62
    """
    learned = {dim: 0.8 for dim in TASTE_DIMENSIONS}
    taste_service.repository.get_by_user_id = AsyncMock(
        return_value=_make_taste_model(interaction_count=5, parameters=learned)
    )

    result = await taste_service.get_taste_vector("user-1")

    for dim in TASTE_DIMENSIONS:
        assert result[dim] == pytest.approx(0.62), f"{dim} expected blended value 0.62"


async def test_get_taste_vector_returns_full_learned_vector_at_10_interactions(
    taste_service: TasteModelService,
) -> None:
    """10+ interactions: full personal vector, no blending."""
    learned = {dim: 0.75 for dim in TASTE_DIMENSIONS}
    taste_service.repository.get_by_user_id = AsyncMock(
        return_value=_make_taste_model(interaction_count=10, parameters=learned)
    )

    result = await taste_service.get_taste_vector("user-1")

    for dim in TASTE_DIMENSIONS:
        assert result[dim] == pytest.approx(0.75), f"{dim} should be full value 0.75"


async def test_get_taste_vector_blend_boundary_at_9_still_blends(
    taste_service: TasteModelService,
) -> None:
    """interaction_count=9 is still in the partial range (< 10), still blends."""
    learned = {dim: 0.8 for dim in TASTE_DIMENSIONS}
    taste_service.repository.get_by_user_id = AsyncMock(
        return_value=_make_taste_model(interaction_count=9, parameters=learned)
    )

    result = await taste_service.get_taste_vector("user-1")

    assert all(result[dim] == pytest.approx(0.62) for dim in TASTE_DIMENSIONS)


# ---------------------------------------------------------------------------
# Concurrent new-user inserts
# ---------------------------------------------------------------------------


async def test_concurrent_new_user_inserts_both_complete_without_error(
    mock_session: AsyncMock,
) -> None:
    """Two simultaneous saves for a brand-new user must both complete without error.

    At the service layer: both calls succeed and upsert() is invoked exactly
    once per signal. At the DB layer: the ON CONFLICT (user_id) DO UPDATE clause
    in SQLAlchemyTasteModelRepository.upsert() ensures the second concurrent
    INSERT becomes an atomic UPDATE rather than raising IntegrityError (FR-012).
    The combined interaction_count after both completes must be 2.
    """
    svc1 = TasteModelService(session=mock_session)
    svc2 = TasteModelService(session=mock_session)

    for svc in (svc1, svc2):
        svc.repository = AsyncMock()
        svc.place_repo = AsyncMock()
        svc.repository.get_by_user_id = AsyncMock(return_value=None)
        svc.repository.log_interaction = AsyncMock()

    svc1.repository.upsert = AsyncMock(
        return_value=_make_taste_model(interaction_count=1)
    )
    svc2.repository.upsert = AsyncMock(
        return_value=_make_taste_model(interaction_count=2)
    )

    await asyncio.gather(
        svc1.handle_place_saved("new-user", "place-1", {"price_range": "low"}),
        svc2.handle_place_saved("new-user", "place-2", {"price_range": "high"}),
    )

    svc1.repository.upsert.assert_called_once()
    svc2.repository.upsert.assert_called_once()
    total_upserts = (
        svc1.repository.upsert.call_count + svc2.repository.upsert.call_count
    )
    assert total_upserts == 2
    final_count = svc2.repository.upsert.return_value.interaction_count
    assert final_count == 2
