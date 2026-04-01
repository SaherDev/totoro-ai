"""Circuit breaker wrapper for enrichers.

Trips on exceptions only (timeout, HTTP error, parse failure).
Returning None is normal enricher behavior — not a failure.
"""

import logging
import time
from enum import Enum

from totoro_ai.core.extraction.models import ExtractionContext

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerEnricher:
    """Wraps an enricher with circuit breaker protection.

    After ``failure_threshold`` consecutive exceptions, the breaker opens
    and skips the enricher for ``cooldown_seconds``. After cooldown, a
    single probe request is allowed (half-open). Success resets the breaker;
    failure re-opens it.
    """

    def __init__(
        self,
        enricher: object,
        failure_threshold: int = 5,
        cooldown_seconds: float = 900.0,
    ) -> None:
        self._enricher = enricher
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_failure_time = 0.0

    async def enrich(self, context: ExtractionContext) -> None:
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed < self._cooldown_seconds:
                logger.debug(
                    "Circuit breaker OPEN for %s, skipping (%.0fs remaining)",
                    type(self._enricher).__name__,
                    self._cooldown_seconds - elapsed,
                )
                return
            self._state = CircuitState.HALF_OPEN
            logger.info(
                "Circuit breaker HALF_OPEN for %s, probing",
                type(self._enricher).__name__,
            )

        try:
            await self._enricher.enrich(context)  # type: ignore[union-attr]
            self._reset()
        except Exception:
            self._record_failure()
            logger.warning(
                "Circuit breaker: %s failed (%d/%d)",
                type(self._enricher).__name__,
                self._consecutive_failures,
                self._failure_threshold,
                exc_info=True,
            )

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()
        if self._consecutive_failures >= self._failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker OPEN for %s after %d failures",
                type(self._enricher).__name__,
                self._consecutive_failures,
            )

    def _reset(self) -> None:
        if self._state != CircuitState.CLOSED:
            logger.info(
                "Circuit breaker CLOSED for %s",
                type(self._enricher).__name__,
            )
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
