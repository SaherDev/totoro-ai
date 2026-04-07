"""Langfuse tracing factory (ADR-025)."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel distinguishes "not yet resolved" from "resolved to None".
_UNSET: object = object()
_client: Any = _UNSET


def get_langfuse_client() -> Any | None:
    """Return Langfuse client or None if not configured.

    Result is cached after the first call — auth_check() makes an HTTP
    round-trip and must not run on every LLM/embedding invocation.

    Returns None (with a one-time warning) when Langfuse SDK is missing or
    credentials are absent. Callers must handle None gracefully.
    """
    global _client
    if _client is not _UNSET:
        return _client

    try:
        import langfuse  # noqa: PLC0415

        client = langfuse.Langfuse()
        client.auth_check()
        _client = client
    except Exception as exc:
        logger.warning("Langfuse tracing disabled: %s", exc)
        _client = None

    return _client
