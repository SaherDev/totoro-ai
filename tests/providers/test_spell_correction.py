"""Factory tests for get_spell_corrector()."""

from unittest.mock import patch

import pytest

from totoro_ai.core.spell_correction.base import SpellCorrectorProtocol
from totoro_ai.providers.spell_correction import get_spell_corrector


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    """Clear lru_cache before and after each test to avoid cross-test contamination."""
    get_spell_corrector.cache_clear()
    yield
    get_spell_corrector.cache_clear()


def test_returns_spell_corrector_protocol() -> None:
    """Test get_spell_corrector() returns SpellCorrectorProtocol instance.

    Expected: Returned instance implements the protocol (has correct() method)
    """
    corrector = get_spell_corrector()
    # Verify the instance satisfies SpellCorrectorProtocol
    assert isinstance(corrector, SpellCorrectorProtocol)
    # Verify it has the correct() method
    assert hasattr(corrector, "correct")
    assert callable(corrector.correct)


def test_singleton_same_instance() -> None:
    """Test that get_spell_corrector() returns same cached instance on multiple calls.

    Critical for avoiding 29 MB dictionary reloads on every request.
    Expected: Both calls return the same object (identity check with `is`)
    """
    first_call = get_spell_corrector()
    second_call = get_spell_corrector()
    # Identity check: must be the exact same object in memory
    assert first_call is second_call


def test_unknown_provider_raises() -> None:
    """Test that an unknown provider name raises ValueError.

    Simulates: Config set to unsupported provider string
    Expected: ValueError with helpful message
    """
    # Mock config to return unknown provider
    with patch(
        "totoro_ai.providers.spell_correction.get_config"
    ) as mock_config:
        mock_config.return_value.spell_correction.provider = "unknown_provider"
        with pytest.raises(ValueError, match="Unsupported spell correction provider"):
            get_spell_corrector()
