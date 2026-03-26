"""Langfuse tracing factory (ADR-025)."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_langfuse_client() -> Any | None:
    """Return Langfuse client or None if not configured.

    Returns None (with a warning) when Langfuse SDK is missing or
    credentials are absent. Callers must handle None gracefully.

    Returns:
        Langfuse client instance if configured, None otherwise
    """
    try:
        import langfuse  # noqa: PLC0415

        client = langfuse.Langfuse()
        client.auth_check()
        return client
    except Exception as exc:
        logger.warning("Langfuse tracing disabled: %s", exc)
        return None
