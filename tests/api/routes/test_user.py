"""Tests for GET /v1/user/context (feature 023)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from totoro_ai.api.deps import get_taste_service
from totoro_ai.api.routes.user import router as user_router
from totoro_ai.core.taste.schemas import (
    Chip,
    ChipStatus,
    TasteProfile,
    UserContext,
)
from totoro_ai.core.taste.service import TasteModelService


def _make_app(taste_service: TasteModelService) -> TestClient:
    app = FastAPI()
    app.include_router(user_router, prefix="/v1")
    app.dependency_overrides[get_taste_service] = lambda: taste_service
    return TestClient(app)


def _stub_service(
    *,
    profile: TasteProfile | None = None,
    user_id: str = "user_abc",
) -> AsyncMock:
    """Build a TasteModelService stub with get_taste_profile + real get_user_context."""
    from totoro_ai.core.taste.service import TasteModelService as _Real

    svc = AsyncMock(spec=_Real)
    svc.get_taste_profile = AsyncMock(return_value=profile)

    # Use the real get_user_context implementation, bind via closure.
    async def _get_user_context(uid: str) -> UserContext:
        from totoro_ai.core.config import get_config
        from totoro_ai.core.taste.schemas import ChipView
        from totoro_ai.core.taste.tier import derive_signal_tier, selection_round_name

        config = get_config()
        stages = config.taste_model.chip_selection_stages
        chip_threshold = config.taste_model.chip_threshold
        p = await svc.get_taste_profile(uid)
        if p is None:
            return UserContext(
                saved_places_count=0,
                signal_tier=derive_signal_tier(0, [], stages, chip_threshold),
                chips=[],
            )
        saved_count = 0
        totals = (
            p.signal_counts.get("totals") if isinstance(p.signal_counts, dict) else None
        )
        if isinstance(totals, dict):
            saved_count = int(totals.get("saves", 0))
        signal_tier = derive_signal_tier(
            signal_count=p.generated_from_log_count,
            chips=p.chips,
            stages=stages,
            chip_threshold=chip_threshold,
        )
        current_sr = selection_round_name(p.generated_from_log_count, stages)
        chips = [
            ChipView(
                label=c.label,
                source_field=c.source_field,
                source_value=c.source_value,
                signal_count=c.signal_count,
                status=c.status,
                selection_round=c.selection_round or current_sr,
            )
            for c in p.chips
        ]
        return UserContext(
            saved_places_count=saved_count,
            signal_tier=signal_tier,
            chips=chips,
        )

    svc.get_user_context = _get_user_context
    return svc


def test_cold_user_returns_cold_tier() -> None:
    svc = _stub_service(profile=None)
    client = _make_app(svc)

    response = client.get("/v1/user/context", params={"user_id": "new_user"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "saved_places_count": 0,
        "signal_tier": "cold",
        "chips": [],
    }


def test_warming_user_returns_warming_tier() -> None:
    profile = TasteProfile(
        taste_profile_summary=[],
        signal_counts={"totals": {"saves": 3}},
        chips=[],
        generated_from_log_count=3,
    )
    svc = _stub_service(profile=profile)
    client = _make_app(svc)

    response = client.get("/v1/user/context", params={"user_id": "warm_user"})

    assert response.status_code == 200
    body = response.json()
    assert body["signal_tier"] == "warming"
    assert body["saved_places_count"] == 3
    assert body["chips"] == []


def test_chip_selection_tier_exposes_pending_chip_shape() -> None:
    chip = Chip(
        label="Ramen lover",
        source_field="attributes.cuisine",
        source_value="ramen",
        signal_count=3,
        status=ChipStatus.PENDING,
        selection_round=None,
    )
    profile = TasteProfile(
        taste_profile_summary=[],
        signal_counts={"totals": {"saves": 5}},
        chips=[chip],
        generated_from_log_count=5,
    )
    svc = _stub_service(profile=profile)
    client = _make_app(svc)

    response = client.get("/v1/user/context", params={"user_id": "chip_user"})

    assert response.status_code == 200
    body = response.json()
    assert body["signal_tier"] == "chip_selection"
    assert len(body["chips"]) == 1
    returned = body["chips"][0]
    assert returned["label"] == "Ramen lover"
    assert returned["status"] == "pending"
    # Pending chips get their selection_round stamped with the current
    # crossed-stage name (here "round_1" for signal_count=5). The frontend
    # can echo this back verbatim in a chip_confirm submission.
    assert returned["selection_round"] == "round_1"


def test_active_tier_preserves_confirmed_and_rejected_statuses() -> None:
    chips = [
        Chip(
            label="Ramen lover",
            source_field="attributes.cuisine",
            source_value="ramen",
            signal_count=5,
            status=ChipStatus.CONFIRMED,
            selection_round="round_1",
        ),
        Chip(
            label="Casual spots",
            source_field="attributes.vibe",
            source_value="casual",
            signal_count=2,
            status=ChipStatus.REJECTED,
            selection_round="round_1",
        ),
    ]
    profile = TasteProfile(
        taste_profile_summary=[],
        signal_counts={"totals": {"saves": 12}},
        chips=chips,
        generated_from_log_count=12,
    )
    svc = _stub_service(profile=profile)
    client = _make_app(svc)

    response = client.get("/v1/user/context", params={"user_id": "active_user"})

    assert response.status_code == 200
    body = response.json()
    assert body["signal_tier"] == "active"
    statuses = {c["label"]: (c["status"], c["selection_round"]) for c in body["chips"]}
    # Confirmed/rejected chips keep their original selection_round, not
    # overwritten by the current stage.
    assert statuses["Ramen lover"] == ("confirmed", "round_1")
    assert statuses["Casual spots"] == ("rejected", "round_1")


def test_chip_selection_at_round_2_stamps_round_2_on_pending_chips() -> None:
    # New pending chip that surfaces after the user crossed round_2.
    chip = Chip(
        label="Pho lover",
        source_field="attributes.cuisine",
        source_value="pho",
        signal_count=3,
        status=ChipStatus.PENDING,
        selection_round=None,
    )
    profile = TasteProfile(
        taste_profile_summary=[],
        signal_counts={"totals": {"saves": 20}},
        chips=[chip],
        generated_from_log_count=20,  # round_2 threshold
    )
    svc = _stub_service(profile=profile)
    client = _make_app(svc)

    response = client.get("/v1/user/context", params={"user_id": "r2_user"})

    body = response.json()
    assert body["signal_tier"] == "chip_selection"
    assert body["chips"][0]["selection_round"] == "round_2"


def test_missing_user_id_returns_422() -> None:
    svc = _stub_service(profile=None)
    client = _make_app(svc)

    response = client.get("/v1/user/context")
    assert response.status_code == 422
