"""Spell correction provider factory.

Resolves configured spell corrector by provider name (ADR-020, ADR-038).
Returns a cached singleton to avoid reloading the 29 MB dictionary per request.
"""

import functools
import logging

from totoro_ai.core.config import get_config
from totoro_ai.core.spell_correction.base import SpellCorrectorProtocol
from totoro_ai.core.spell_correction.symspell import SymSpellCorrector

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_spell_corrector() -> SpellCorrectorProtocol:
    """Get spell corrector singleton for the configured provider.

    Reads spell_correction.provider from config/app.yaml. The factory loads the
    corrector once on the first call and returns the cached instance on all
    subsequent calls (including per-request Depends() invocations).

    CRITICAL: SymSpellCorrector.__init__ loads a 29 MB dictionary from disk.
    @lru_cache(maxsize=1) ensures this happens exactly once per process, never
    per-request. This is the only correct way to use SymSpellCorrector with FastAPI.

    Returns:
        Spell corrector instance implementing SpellCorrectorProtocol

    Raises:
        ValueError: If provider is unsupported
    """
    provider = get_config().spell_correction.provider

    if provider == "symspell":
        return SymSpellCorrector()

    raise ValueError(f"Unsupported spell correction provider: {provider}")
