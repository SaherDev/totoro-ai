"""Tests for GooglePlacesClient match-quality classification logic."""

from unittest.mock import AsyncMock, MagicMock, patch

from totoro_ai.core.extraction.places_client import (
    GooglePlacesClient,
    PlacesMatchQuality,
    _core_tokens,
)


def _fake_response(name: str, place_id: str = "place_123") -> MagicMock:
    """Build a fake httpx.Response wrapping a minimal Places API payload."""
    payload = {
        "candidates": [
            {
                "name": name,
                "place_id": place_id,
                "geometry": {"location": {"lat": 13.7, "lng": 100.5}},
            }
        ]
    }
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _patched_client() -> GooglePlacesClient:
    """Return a GooglePlacesClient with secrets + config mocked out."""
    with patch(
        "totoro_ai.core.extraction.places_client.get_secrets"
    ) as mock_secrets, patch(
        "totoro_ai.core.extraction.places_client.get_config"
    ) as mock_config:
        mock_secrets.return_value.providers.google.api_key = "fake-key"
        cfg = MagicMock()
        cfg.external_services.google_places.base_url = (
            "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        )
        cfg.external_services.google_places.timeout_seconds = 5.0
        cfg.external_services.google_places.request_fields = [
            "name",
            "place_id",
            "geometry",
        ]
        mock_config.return_value = cfg
        return GooglePlacesClient()


# ---------------------------------------------------------------------------
# _core_tokens unit tests
# ---------------------------------------------------------------------------


def test_core_tokens_removes_city_noise() -> None:
    assert _core_tokens("RAMEN KAISUGI Bangkok") == "kaisugi"


def test_core_tokens_removes_street_noise() -> None:
    assert _core_tokens("RAMEN KAISUGI Sukhumvit 33") == "kaisugi"


def test_core_tokens_lowercases_and_strips_punctuation() -> None:
    assert _core_tokens("Ramen Kaisugi!") == "kaisugi"


def test_core_tokens_plain_venue_name() -> None:
    assert _core_tokens("Ramen Kaisugi") == "kaisugi"


def test_core_tokens_fallback_when_all_noise() -> None:
    """If every token is noise, return the cleaned string rather than empty."""
    result = _core_tokens("Bangkok Road")
    # "bangkok" and "road" both noise — fallback returns cleaned original
    assert result != ""


# ---------------------------------------------------------------------------
# Classification: EXACT
# ---------------------------------------------------------------------------


async def test_identical_name_is_exact() -> None:
    """Candidate name matching Google name exactly → EXACT."""
    client = _patched_client()
    response = _fake_response("Ramen Kaisugi")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        result = await client.validate_place("Ramen Kaisugi", location=None)

    assert result.match_quality == PlacesMatchQuality.EXACT


async def test_case_insensitive_name_is_exact() -> None:
    """Candidate name in ALL CAPS matching Google name → EXACT."""
    client = _patched_client()
    response = _fake_response("Ramen Kaisugi")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        result = await client.validate_place("RAMEN KAISUGI", location=None)

    assert result.match_quality == PlacesMatchQuality.EXACT


async def test_name_with_city_suffix_is_exact() -> None:
    """City suffix in candidate name is stripped as noise → EXACT.

    "RAMEN KAISUGI Bangkok" vs "Ramen Kaisugi":
    core both → "kaisugi" → ratio 1.0.
    """
    client = _patched_client()
    response = _fake_response("Ramen Kaisugi")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        result = await client.validate_place(
            "RAMEN KAISUGI Bangkok", location="Bangkok"
        )

    assert result.match_quality == PlacesMatchQuality.EXACT


async def test_name_with_wrong_city_field_still_exact() -> None:
    """When NER sets city to a street name, token approach is still robust.

    location="Sukhumvit 33" (wrong — NER confused street for city).
    Candidate name "RAMEN KAISUGI Bangkok" still compares as "kaisugi".
    The suffix strip would have failed here; token approach does not.
    """
    client = _patched_client()
    response = _fake_response("Ramen Kaisugi")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        result = await client.validate_place(
            "RAMEN KAISUGI Bangkok", location="Sukhumvit 33"
        )

    assert result.match_quality == PlacesMatchQuality.EXACT


async def test_name_with_street_in_candidate_name_is_exact() -> None:
    """Street address in candidate name is stripped as noise → EXACT.

    "RAMEN KAISUGI Sukhumvit 33" vs "Ramen Kaisugi":
    core both → "kaisugi" → ratio 1.0.
    """
    client = _patched_client()
    response = _fake_response("Ramen Kaisugi")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        result = await client.validate_place(
            "RAMEN KAISUGI Sukhumvit 33", location=None
        )

    assert result.match_quality == PlacesMatchQuality.EXACT


async def test_emoji_prefix_candidate_name_is_exact() -> None:
    """emoji_regex candidate "RAMEN KAISUGI Bangkok" (from 📍 capture) → EXACT."""
    client = _patched_client()
    response = _fake_response("Ramen Kaisugi")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        result = await client.validate_place(
            "RAMEN KAISUGI Bangkok", location="Bangkok"
        )

    assert result.match_quality == PlacesMatchQuality.EXACT


# ---------------------------------------------------------------------------
# Classification: FUZZY
# ---------------------------------------------------------------------------


async def test_close_but_not_exact_is_fuzzy() -> None:
    """Core token ratio ≥ 0.70 but < 0.85 → FUZZY.

    "Fuji Ramen" → core "fuji"
    Google "Fujiya Ramen" → core "fujiya"
    SequenceMatcher("fuji", "fujiya") = 8/10 = 0.80 → FUZZY.
    """
    client = _patched_client()
    response = _fake_response("Fujiya Ramen")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        result = await client.validate_place("Fuji Ramen", location=None)

    assert result.match_quality == PlacesMatchQuality.FUZZY


# ---------------------------------------------------------------------------
# Classification: CATEGORY_ONLY
# ---------------------------------------------------------------------------


async def test_unrelated_name_is_category_only() -> None:
    """Low core-token similarity → CATEGORY_ONLY."""
    client = _patched_client()
    response = _fake_response("Nakatani Sushi")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        result = await client.validate_place("Ramen Kaisugi", location=None)

    assert result.match_quality == PlacesMatchQuality.CATEGORY_ONLY


# ---------------------------------------------------------------------------
# No candidates → NONE
# ---------------------------------------------------------------------------


async def test_no_candidates_returns_none_quality() -> None:
    """Empty candidates list → NONE match quality."""
    client = _patched_client()
    resp = MagicMock()
    resp.json.return_value = {"candidates": []}
    resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=resp):
        result = await client.validate_place("Unknown Place", location=None)

    assert result.match_quality == PlacesMatchQuality.NONE
    assert result.external_id is None
