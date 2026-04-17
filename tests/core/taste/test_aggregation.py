"""Tests for aggregate_signal_counts (ADR-058)."""

from __future__ import annotations

from totoro_ai.core.places.models import LocationContext, PlaceAttributes
from totoro_ai.core.taste.aggregation import aggregate_signal_counts
from totoro_ai.core.taste.schemas import InteractionRow

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _row(
    type: str = "save",
    place_type: str = "restaurant",
    subcategory: str | None = None,
    source: str | None = None,
    tags: list[str] | None = None,
    cuisine: str | None = None,
    price_hint: str | None = None,
    ambiance: str | None = None,
    dietary: list[str] | None = None,
    good_for: list[str] | None = None,
    location_context: LocationContext | None = None,
) -> InteractionRow:
    return InteractionRow(
        type=type,
        place_type=place_type,
        subcategory=subcategory,
        source=source,
        tags=tags or [],
        attributes=PlaceAttributes(
            cuisine=cuisine,
            price_hint=price_hint,
            ambiance=ambiance,
            dietary=dietary or [],
            good_for=good_for or [],
            location_context=location_context,
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_rows() -> None:
    counts = aggregate_signal_counts([])

    assert counts.totals.saves == 0
    assert counts.totals.accepted == 0
    assert counts.totals.rejected == 0
    assert counts.totals.onboarding_confirmed == 0
    assert counts.totals.onboarding_dismissed == 0
    assert counts.place_type == {}
    assert counts.subcategory == {}
    assert counts.source == {}
    assert counts.tags == {}


def test_save_only() -> None:
    rows = [
        _row(
            type="save",
            place_type="restaurant",
            subcategory="italian",
            source="google_maps",
            cuisine="italian",
            price_hint="$$",
        ),
        _row(
            type="save",
            place_type="restaurant",
            subcategory="japanese",
            source="manual",
            cuisine="japanese",
            price_hint="$$$",
        ),
    ]
    counts = aggregate_signal_counts(rows)

    assert counts.totals.saves == 2
    assert counts.totals.accepted == 0
    assert counts.place_type == {"restaurant": 2}
    assert counts.subcategory == {
        "restaurant": {"italian": 1, "japanese": 1},
    }
    assert counts.source == {"google_maps": 1, "manual": 1}
    assert counts.attributes.cuisine == {"italian": 1, "japanese": 1}
    assert counts.attributes.price_hint == {"$$": 1, "$$$": 1}


def test_mixed_types() -> None:
    rows = [
        _row(type="save", place_type="restaurant", subcategory="thai"),
        _row(type="accepted", place_type="cafe", subcategory="coffee_shop"),
        _row(type="rejected", place_type="bar", subcategory="dive_bar"),
    ]
    counts = aggregate_signal_counts(rows)

    assert counts.totals.saves == 1
    assert counts.totals.accepted == 1
    assert counts.totals.rejected == 1

    # Positive types feed main tree
    assert counts.place_type == {"restaurant": 1, "cafe": 1}
    assert "restaurant" in counts.subcategory
    assert "cafe" in counts.subcategory

    # Rejected feeds rejected branch, not main tree
    assert "bar" not in counts.place_type
    assert "bar" in counts.rejected.subcategory


def test_rejection_feeds_rejected_branch() -> None:
    rows = [
        _row(
            type="rejected",
            place_type="restaurant",
            subcategory="fast_food",
            cuisine="american",
            ambiance="casual",
        ),
        _row(
            type="onboarding_dismiss",
            place_type="bar",
            subcategory="sports_bar",
            cuisine="pub_food",
        ),
    ]
    counts = aggregate_signal_counts(rows)

    assert counts.totals.rejected == 1
    assert counts.totals.onboarding_dismissed == 1

    # Main tree should be empty
    assert counts.place_type == {}
    assert counts.subcategory == {}
    assert counts.attributes.cuisine == {}
    assert counts.attributes.ambiance == {}

    # Rejected branch populated
    assert counts.rejected.subcategory == {
        "restaurant": {"fast_food": 1},
        "bar": {"sports_bar": 1},
    }
    assert counts.rejected.attributes.cuisine == {"american": 1, "pub_food": 1}
    assert counts.rejected.attributes.ambiance == {"casual": 1}


def test_source_counted_only_for_saves() -> None:
    rows = [
        _row(type="save", source="google_maps"),
        _row(type="accepted", source="recommendation"),
        _row(type="onboarding_confirm", source="onboarding_ui"),
    ]
    counts = aggregate_signal_counts(rows)

    # Only the save's source is counted
    assert counts.source == {"google_maps": 1}
    assert "recommendation" not in counts.source
    assert "onboarding_ui" not in counts.source


def test_multiple_tags() -> None:
    rows = [
        _row(type="save", tags=["date-night", "outdoor-seating"]),
        _row(type="accepted", tags=["date-night", "romantic"]),
    ]
    counts = aggregate_signal_counts(rows)

    assert counts.tags == {"date-night": 2, "outdoor-seating": 1, "romantic": 1}


def test_location_context() -> None:
    loc = LocationContext(
        neighborhood="Williamsburg", city="New York", country="US"
    )
    rows = [
        _row(type="save", location_context=loc),
        _row(
            type="accepted",
            location_context=LocationContext(city="New York", country="US"),
        ),
    ]
    counts = aggregate_signal_counts(rows)

    lc = counts.attributes.location_context
    assert lc.neighborhood == {"Williamsburg": 1}
    assert lc.city == {"New York": 2}
    assert lc.country == {"US": 2}
