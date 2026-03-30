"""Spell correction provider protocol.

Defines the interface for swappable spell correction implementations (ADR-038).
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class SpellCorrectorProtocol(Protocol):
    """Protocol for spell correction providers."""

    def correct(self, text: str, language: str = "en") -> str:
        """Return corrected text, preserving original on any error.

        Args:
            text: The text to correct
            language: Language code (default: "en" for English)

        Returns:
            Corrected text, or original text if correction failed or made no changes
        """
        ...
