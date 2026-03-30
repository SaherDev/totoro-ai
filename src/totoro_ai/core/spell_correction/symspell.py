"""SymSpell-based spell corrector implementation.

Wraps symspellpy for multi-word spell correction with URL preservation (ADR-038).
Dictionary loaded via importlib.resources (Python 3.11+ native, avoiding
deprecated pkg_resources).
"""

import logging
import urllib.parse
from importlib import resources

logger = logging.getLogger(__name__)


class SymSpellCorrector:
    """SymSpell-based corrector. Preserves URLs and proper nouns.

    WARNING: __init__ loads a 29 MB dictionary from disk. This instance MUST be
    constructed exactly once and reused (via @functools.lru_cache singleton factory).
    Never construct per-request.
    """

    def __init__(self, max_edit_distance: int = 2) -> None:
        """Initialize SymSpell corrector with bundled English dictionary.

        Args:
            max_edit_distance: Max edit distance for correction (default: 2)

        Raises:
            RuntimeError: If dictionary fails to load
        """
        try:
            import symspellpy  # type: ignore[import-untyped]  # noqa: PLC0415

            self._sym_spell = symspellpy.SymSpell(
                max_dictionary_edit_distance=max_edit_distance, prefix_length=7
            )
            # Load bundled English frequency dictionary
            dict_path = resources.files("symspellpy").joinpath(
                "frequency_dictionary_en_82_765.txt"
            )
            self._sym_spell.load_dictionary(
                str(dict_path), term_index=0, count_index=1
            )
        except Exception as e:
            logger.error("Failed to initialize SymSpellCorrector: %s", e)
            raise RuntimeError(f"Failed to load SymSpell dictionary: {e}") from e

    def correct(self, text: str, language: str = "en") -> str:
        """Return corrected text, preserving original on any error.

        URL tokens (http://, https://) are never passed to the corrector.
        Unrecognized terms (proper nouns, foreign words) are preserved unchanged.

        Args:
            text: The text to correct
            language: Language code (ignored in this iteration; always English)

        Returns:
            Corrected text, or original text on any error
        """
        try:
            corrected = self._correct_non_url_tokens(text)
            if corrected != text:
                logger.info(
                    "Spell correction applied | input: %r → output: %r",
                    text,
                    corrected,
                )
            else:
                logger.debug("No corrections needed | input: %r", text)
            return corrected
        except Exception as e:
            logger.warning(
                "Spell correction failed for input: %r, returning original: %s",
                text,
                e,
            )
            return text

    def _correct_non_url_tokens(self, text: str) -> str:
        """Correct text while preserving URL tokens.

        Tokenizes on whitespace, separates URLs from regular text, corrects
        regular text, and reassembles with URLs at their original positions.

        Args:
            text: The text to correct

        Returns:
            Corrected text with URL tokens preserved
        """
        tokens = text.split()
        url_indices = {}
        non_url_tokens = []

        # Separate URL tokens from non-URL tokens, remembering URL positions
        for i, token in enumerate(tokens):
            parsed = urllib.parse.urlparse(token)
            if parsed.scheme in ("http", "https"):
                url_indices[i] = token
            else:
                non_url_tokens.append(token)

        # Log URL preservation
        if url_indices:
            logger.debug(
                "📌 Found %d URL(s) to preserve: %s",
                len(url_indices),
                [url_indices[i] for i in sorted(url_indices.keys())],
            )

        # If no URLs, correct the entire text
        if not url_indices:
            logger.debug("🔍 No URLs found, correcting entire text")
            suggestions = self._sym_spell.lookup_compound(text, max_edit_distance=2)
            return suggestions[0].term if suggestions else text

        # Correct only non-URL text
        non_url_text = " ".join(non_url_tokens)
        logger.debug("🔍 Correcting non-URL text: %r", non_url_text)
        suggestions = self._sym_spell.lookup_compound(non_url_text, max_edit_distance=2)
        corrected_non_url = suggestions[0].term if suggestions else non_url_text
        if corrected_non_url != non_url_text:
            logger.debug("✨ Non-URL correction: %r → %r", non_url_text, corrected_non_url)

        # Reassemble: rebuild token list with corrected non-URL tokens and original URLs
        corrected_tokens = corrected_non_url.split()
        result_tokens = []
        non_url_token_idx = 0

        for i in range(len(tokens)):
            if i in url_indices:
                result_tokens.append(url_indices[i])
            else:
                if non_url_token_idx < len(corrected_tokens):
                    result_tokens.append(corrected_tokens[non_url_token_idx])
                    non_url_token_idx += 1

        return " ".join(result_tokens)
