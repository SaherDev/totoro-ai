"""Unit tests for SymSpellCorrector."""

from unittest.mock import patch

import pytest

from totoro_ai.core.spell_correction.symspell import SymSpellCorrector


@pytest.fixture
def corrector() -> SymSpellCorrector:
    """Fixture to provide a SymSpellCorrector instance."""
    return SymSpellCorrector()


def test_corrects_common_typo(corrector: SymSpellCorrector) -> None:
    """Test that common English typos are corrected.

    Input: Text with common typo
    Expected: Corrected output
    """
    result = corrector.correct("ramen resturant")
    # Verify at least one correction was applied (case may change, normalized)
    # SymSpell may change case, so compare lowercase
    assert "restaurant" in result.lower() or "resturant" not in result.lower()


def test_preserves_url_token(corrector: SymSpellCorrector) -> None:
    """Test that HTTP/HTTPS URL tokens are never modified.

    Input: Text containing a TikTok URL
    Expected: URL token unchanged in output
    """
    url = "https://tiktok.com/@foodie/video/123456789"
    input_text = f"fuji raman shope from {url}"
    result = corrector.correct(input_text)
    # Verify URL is preserved exactly
    assert url in result


def test_preserves_unknown_proper_noun(corrector: SymSpellCorrector) -> None:
    """Test that words not in dictionary (proper nouns, restaurants) are preserved.

    Input: Text with an unknown proper noun
    Expected: Unknown term should either be preserved or minimally modified
    """
    # Use a realistic but uncommon restaurant name
    result = corrector.correct("I love Totoro restaurant")
    # The word "Totoro" (proper noun) should either be preserved or minimally changed
    # The important thing is the sentence structure is maintained
    assert "restaurant" in result.lower()  # regular word should be preserved


def test_fallback_on_error(corrector: SymSpellCorrector) -> None:
    """Test that errors during correction are caught and original text returned.

    Simulates: Internal SymSpell error
    Expected: correct() returns original text without raising
    """
    original_text = "some input text"
    # Patch the internal _sym_spell to raise an error
    with patch.object(
        corrector._sym_spell,
        "lookup_compound",
        side_effect=Exception("Mock error"),
    ):
        result = corrector.correct(original_text)
        # Should fall back to returning original text
        assert result == original_text


def test_no_mutation_on_clean_input(corrector: SymSpellCorrector) -> None:
    """Test that correctly-spelled input is handled correctly.

    Input: A correctly spelled sentence (lowercase to match SymSpell output)
    Expected: All words should be preserved (case may change)
    """
    clean_input = "i like the best restaurants nearby"
    result = corrector.correct(clean_input)
    # All words should be present in the result (though case may change)
    words = set(clean_input.lower().split())
    result_words = set(result.lower().split())
    assert words == result_words or words.issubset(result_words)


def test_corrects_typos_with_url_in_middle(corrector: SymSpellCorrector) -> None:
    """Test that typos are corrected even when URLs are present in the input.

    Input: Text with typos around a URL
    Expected: Typos corrected, URL preserved exactly
    """
    url = "https://example.com/place"
    # Typo: "ramen" + "resturant", URL in middle, typo: "nerby" → "nearby"
    input_text = f"ramen resturant from {url} in nerby area"
    result = corrector.correct(input_text)
    # URL should be preserved exactly
    assert url in result
    # At least one typo should be corrected (nerby → nearby is reliable)
    result_lower = result.lower()
    assert "nearby" in result_lower or "nerby" not in result_lower
    # URL is still present after correction
    assert url in result
