"""Unit tests for circuit breaker."""

import pytest

from totoro_ai.core.extraction.circuit_breaker import (
    CircuitBreakerEnricher,
    CircuitState,
)
from totoro_ai.core.extraction.models import ExtractionContext


class FailingEnricher:
    async def enrich(self, context: ExtractionContext) -> None:
        raise RuntimeError("boom")


class SuccessEnricher:
    def __init__(self) -> None:
        self.call_count = 0

    async def enrich(self, context: ExtractionContext) -> None:
        self.call_count += 1


class CountingEnricher:
    def __init__(self, fail_until: int = 0) -> None:
        self.call_count = 0
        self._fail_until = fail_until

    async def enrich(self, context: ExtractionContext) -> None:
        self.call_count += 1
        if self.call_count <= self._fail_until:
            raise RuntimeError(f"fail #{self.call_count}")


def _make_context() -> ExtractionContext:
    return ExtractionContext(url=None, user_id="u1")


@pytest.mark.asyncio
class TestCircuitBreaker:
    async def test_closed_passes_through(self) -> None:
        inner = SuccessEnricher()
        cb = CircuitBreakerEnricher(inner, failure_threshold=5)
        await cb.enrich(_make_context())
        assert inner.call_count == 1

    async def test_trips_after_threshold(self) -> None:
        inner = FailingEnricher()
        cb = CircuitBreakerEnricher(inner, failure_threshold=3, cooldown_seconds=900)
        for _ in range(3):
            await cb.enrich(_make_context())
        assert cb._state == CircuitState.OPEN

    async def test_open_skips_calls(self) -> None:
        inner = FailingEnricher()
        cb = CircuitBreakerEnricher(inner, failure_threshold=2, cooldown_seconds=900)
        # Trip the breaker
        await cb.enrich(_make_context())
        await cb.enrich(_make_context())
        assert cb._state == CircuitState.OPEN

        # Now wrap with a success enricher — should be skipped
        success = SuccessEnricher()
        cb._enricher = success
        await cb.enrich(_make_context())
        assert success.call_count == 0  # Skipped because open

    async def test_success_resets_to_closed(self) -> None:
        inner = CountingEnricher(fail_until=2)
        cb = CircuitBreakerEnricher(inner, failure_threshold=5)
        # Two failures, then a success
        await cb.enrich(_make_context())  # fail 1
        await cb.enrich(_make_context())  # fail 2
        assert cb._consecutive_failures == 2
        await cb.enrich(_make_context())  # success
        assert cb._state == CircuitState.CLOSED
        assert cb._consecutive_failures == 0

    async def test_half_open_probes(self) -> None:
        inner = FailingEnricher()
        cb = CircuitBreakerEnricher(inner, failure_threshold=1, cooldown_seconds=0)
        await cb.enrich(_make_context())  # trips
        assert cb._state == CircuitState.OPEN

        # With cooldown=0, next call should probe (half-open)
        success = SuccessEnricher()
        cb._enricher = success
        await cb.enrich(_make_context())
        assert success.call_count == 1
        assert cb._state == CircuitState.CLOSED
