"""LLM provider factory - resolves configured LLM clients by role."""

from collections.abc import AsyncGenerator
from typing import Any

import anthropic

from totoro_ai.core.config import load_yaml_config


def _load_local_config() -> dict[str, Any]:
    """Load config/.local.yaml secrets, returning empty dict if missing."""
    try:
        result: dict[str, Any] = load_yaml_config(".local.yaml")
        return result
    except FileNotFoundError:
        return {}


class AnthropicLLMClient:
    """Anthropic LLM client implementing LLMClientProtocol."""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        """Initialize async Anthropic client with specified model.

        Args:
            model: Model identifier (e.g., 'claude-sonnet-4-6')
            api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        """
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def stream(
        self, system: str, user_message: str
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from Anthropic Claude asynchronously.

        Args:
            system: System prompt
            user_message: User message/query

        Yields:
            Individual tokens as they are generated
        """
        async with self._client.messages.stream(
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_message}],
            model=self._model,
        ) as stream:
            async for text in stream.text_stream:
                yield text


def get_llm(role: str) -> AnthropicLLMClient:
    """Get LLM client for the specified role.

    Resolves model from config/models.yaml based on role.

    Args:
        role: Logical role (e.g., 'orchestrator', 'intent_parser', 'embedder')

    Returns:
        LLM client instance

    Raises:
        KeyError: If role not found in config
    """
    config: dict[str, Any] = load_yaml_config("models.yaml")
    role_config: dict[str, Any] = config[role]

    provider: str = role_config["provider"]
    model: str = role_config["model"]

    if provider == "anthropic":
        local: dict[str, Any] = _load_local_config()
        api_key: str | None = local.get("providers", {}).get("anthropic", {}).get("api_key")
        return AnthropicLLMClient(model=model, api_key=api_key)

    raise ValueError(f"Unsupported provider: {provider}")
