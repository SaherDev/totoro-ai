"""Tracing provider abstraction (ADR-025).

Callers depend on TracingClient / TracingSpan protocols.
The Langfuse adapter is the default implementation; swap by returning a
different adapter from get_tracing_client().
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class TracingSpan(Protocol):
    def end(self, output: dict[str, Any] | None = None, level: str = "DEFAULT") -> None:
        ...


@runtime_checkable
class TracingClient(Protocol):
    def generation(
        self,
        name: str,
        input: Any = None,
        model: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> TracingSpan:
        ...

    def capture_message(
        self,
        message: str,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        ...

    def flush(self) -> None:
        ...


# ---------------------------------------------------------------------------
# Null adapter (no-op — used when Langfuse is not configured)
# ---------------------------------------------------------------------------


class _NullSpan:
    def end(self, output: dict[str, Any] | None = None, level: str = "DEFAULT") -> None:
        pass


class _NullTracingClient:
    def generation(
        self,
        name: str,
        input: Any = None,
        model: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> _NullSpan:
        return _NullSpan()

    def capture_message(
        self,
        message: str,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        pass

    def flush(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Langfuse adapter
# ---------------------------------------------------------------------------


class _LangfuseSpan:
    def __init__(self, generation: Any) -> None:
        self._generation = generation

    def end(self, output: dict[str, Any] | None = None, level: str = "DEFAULT") -> None:
        if output is not None:
            self._generation.update(output=output)
        self._generation.end()


class _LangfuseTracingClient:
    def __init__(self, client: Any) -> None:
        self._client = client

    def generation(
        self,
        name: str,
        input: Any = None,
        model: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> _LangfuseSpan:
        try:
            span = self._client.start_span(name=name)
            trace_kwargs: dict[str, Any] = {}
            if user_id is not None:
                trace_kwargs["user_id"] = user_id
            if session_id is not None:
                trace_kwargs["session_id"] = session_id
            if trace_kwargs:
                span.update_trace(**trace_kwargs)
            gen_kwargs: dict[str, Any] = {"name": name}
            if input is not None:
                gen_kwargs["input"] = input
            if model is not None:
                gen_kwargs["model"] = model
            gen = span.start_observation(as_type="generation", **gen_kwargs)
            return _LangfuseSpan(gen)
        except Exception as exc:
            logger.warning("Langfuse generation setup failed: %s", exc)
            return _NullSpan()

    def capture_message(
        self,
        message: str,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        try:
            span = self._client.start_span(name=message)
            if user_id is not None or session_id is not None:
                span.update_trace(user_id=user_id, session_id=session_id)
            span.start_observation(
                as_type="event",
                name=message,
                input={"level": level, **(metadata or {})},
            ).end()
            span.end()
        except Exception as exc:
            logger.warning("Langfuse capture_message failed: %s", exc)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception as exc:
            logger.warning("Langfuse flush failed: %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_UNSET: object = object()
_client: _LangfuseTracingClient | _NullTracingClient | object = _UNSET


def get_tracing_client() -> TracingClient:
    """Return a TracingClient. Always returns a valid client — never None.

    Result is cached after first call. Falls back to a no-op client when
    Langfuse SDK is missing or credentials are absent.
    """
    global _client
    if _client is not _UNSET:
        return _client  # type: ignore[return-value]

    try:
        import langfuse  # noqa: PLC0415

        from totoro_ai.core.config import get_secrets  # noqa: PLC0415

        secrets = get_secrets()
        lf = langfuse.Langfuse(
            public_key=secrets.LANGFUSE_PUBLIC_KEY,
            secret_key=secrets.LANGFUSE_SECRET_KEY,
            host=secrets.LANGFUSE_HOST,
        )
        lf.auth_check()
        _client = _LangfuseTracingClient(lf)
    except Exception as exc:
        logger.warning("Langfuse tracing disabled: %s", exc)
        _client = _NullTracingClient()

    assert isinstance(_client, (_LangfuseTracingClient, _NullTracingClient))
    return _client
