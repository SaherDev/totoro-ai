"""Unit tests for PlacesRepo — SQL logic via mock AsyncSession."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql as pg_dialect

from totoro_ai.core.places_v2.models import (
    LocationContext,
    PlaceCategory,
    PlaceCore,
    PlaceQuery,
)
from totoro_ai.core.places_v2.places_repo import PlacesRepo, _core_to_dict, _row_to_core
from totoro_ai.core.places_v2.tags import CuisineTag


def _make_repo(rows: list[dict] | None = None) -> tuple[PlacesRepo, MagicMock]:
    session = MagicMock()
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(
        return_value=iter([MagicMock(_mapping=r) for r in (rows or [])])
    )
    mock_result.mappings = MagicMock(
        return_value=MagicMock(one=MagicMock(return_value={}))
    )
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    return PlacesRepo(session), session


def _minimal_row(
    pid: str = "p1",
    provider_id: str = "google:abc",
) -> dict:
    return {
        "id": pid,
        "provider_id": provider_id,
        "place_name": f"Place {pid}",
        "category": None,
        "tags": None,
        "location": None,
        "created_at": datetime.now(UTC),
        "refreshed_at": None,
    }


# ---------------------------------------------------------------------------
# _row_to_core
# ---------------------------------------------------------------------------

class TestRowToCore:
    def test_minimal_row(self) -> None:
        row = _minimal_row()
        core = _row_to_core(row)
        assert core.id == "p1"
        assert core.provider_id == "google:abc"
        assert core.place_name == "Place p1"
        assert core.tags == []
        assert core.location is None

    def test_with_tags(self) -> None:
        row = _minimal_row()
        row["tags"] = [{"type": "cuisine", "value": "Thai", "source": "google"}]
        core = _row_to_core(row)
        assert len(core.tags) == 1
        assert core.tags[0].value == "Thai"

    def test_with_location(self) -> None:
        row = _minimal_row()
        row["location"] = {"lat": 13.7, "lng": 100.5, "address": "Test St"}
        core = _row_to_core(row)
        assert core.location is not None
        assert core.location.lat == 13.7

    def test_with_category(self) -> None:
        row = _minimal_row()
        row["category"] = "restaurant"
        core = _row_to_core(row)
        assert core.category == PlaceCategory.restaurant


# ---------------------------------------------------------------------------
# _core_to_dict
# ---------------------------------------------------------------------------

class TestCoreToDict:
    def test_generates_id_when_none(self) -> None:
        core = PlaceCore(place_name="Test", provider_id="google:x")
        now = datetime.now(UTC)
        d = _core_to_dict(core, now)
        assert d["id"] is not None
        assert isinstance(d["id"], str)

    def test_preserves_existing_id(self) -> None:
        core = PlaceCore(id="fixed-id", place_name="Test", provider_id="google:x")
        d = _core_to_dict(core, datetime.now(UTC))
        assert d["id"] == "fixed-id"

    def test_empty_tags_stored_as_none(self) -> None:
        core = PlaceCore(place_name="Test", provider_id="google:x")
        d = _core_to_dict(core, datetime.now(UTC))
        assert d["tags"] is None

    def test_location_serialised(self) -> None:
        core = PlaceCore(
            place_name="Test",
            provider_id="google:x",
            location=LocationContext(lat=13.7, lng=100.5),
        )
        d = _core_to_dict(core, datetime.now(UTC))
        assert d["location"] == {"lat": 13.7, "lng": 100.5}


# ---------------------------------------------------------------------------
# get_by_ids
# ---------------------------------------------------------------------------

class TestGetByIds:
    async def test_empty_input_returns_empty(self) -> None:
        repo, session = _make_repo()
        result = await repo.get_by_ids([])
        assert result == []
        session.execute.assert_not_called()

    async def test_returns_parsed_cores(self) -> None:
        row = _minimal_row("a", "google:a")
        repo, _ = _make_repo([row])
        result = await repo.get_by_ids(["a"])
        assert len(result) == 1
        assert result[0].id == "a"


# ---------------------------------------------------------------------------
# get_by_provider_ids
# ---------------------------------------------------------------------------

class TestGetByProviderIds:
    async def test_empty_input_returns_empty(self) -> None:
        repo, session = _make_repo()
        result = await repo.get_by_provider_ids([])
        assert result == {}
        session.execute.assert_not_called()

    async def test_returns_dict_keyed_by_provider_id(self) -> None:
        row = _minimal_row("a", "google:a")
        repo, _ = _make_repo([row])
        result = await repo.get_by_provider_ids(["google:a"])
        assert "google:a" in result
        assert result["google:a"].provider_id == "google:a"


# ---------------------------------------------------------------------------
# find — filter conditions
# ---------------------------------------------------------------------------

class TestFind:
    async def test_empty_query_executes(self) -> None:
        repo, session = _make_repo([])
        result = await repo.find(PlaceQuery())
        assert result == []
        session.execute.assert_awaited_once()

    async def test_place_name_filter_applied(self) -> None:
        repo, session = _make_repo([])
        await repo.find(PlaceQuery(place_name="ramen"))
        stmt = session.execute.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ramen" in compiled.lower()

    async def test_category_filter_applied(self) -> None:
        repo, session = _make_repo([])
        await repo.find(PlaceQuery(category=PlaceCategory.cafe))
        stmt = session.execute.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "cafe" in compiled.lower()

    async def test_tag_filter_applied(self) -> None:
        repo, session = _make_repo([])
        await repo.find(PlaceQuery(tags=[CuisineTag.thai]))
        stmt = session.execute.call_args.args[0]
        compiled = stmt.compile(dialect=pg_dialect.dialect())
        # JSONB containment operator present and "Thai" in bound parameter value
        assert "@>" in str(compiled)
        assert any("Thai" in str(v) for v in compiled.params.values())

    async def test_limit_passed(self) -> None:
        repo, session = _make_repo([])
        await repo.find(PlaceQuery(), limit=5)
        stmt = session.execute.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "5" in compiled


# ---------------------------------------------------------------------------
# upsert_place — warns when provider_id is None
# ---------------------------------------------------------------------------

class TestUpsertPlace:
    async def test_warns_when_no_provider_id(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        row = _minimal_row("x", "google:x")
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.mappings = MagicMock(
            return_value=MagicMock(one=MagicMock(return_value=row))
        )
        session.execute = AsyncMock(return_value=mock_result)

        core = PlaceCore(place_name="Orphan Place")
        with caplog.at_level("WARNING"):
            await repo.upsert_place(core)

        assert "upsert_place_no_provider_id" in caplog.text
