"""LLM provider factory - resolves configured LLM clients by role."""

from collections.abc import AsyncGenerator
from typing import Any, Protocol, cast, runtime_checkable

import anthropic
import openai
from anthropic.types import MessageParam, TextBlock
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageParam

from totoro_ai.core.config import load_yaml_config


def _load_local_config() -> dict[str, Any]:
    """Load config/.local.yaml secrets, returning empty dict if missing."""
    try:
        result: dict[str, Any] = load_yaml_config(".local.yaml")
        return result
    except FileNotFoundError:
        return {}


# --- Protocol ---


@runtime_checkable
class LLMClientProtocol(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> Any: ...
    def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str, None]: ...


# --- Implementations ---


class AnthropicLLMClient:
    """Anthropic LLM client implementing LLMClientProtocol."""

    def __init__(
        self,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 1.0,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @staticmethod
    def _split_messages(
        messages: list[dict[str, str]],
    ) -> tuple[str | None, list[MessageParam]]:
        """Extract system message and return (system, user_messages).

        Anthropic requires system prompt as a top-level kwarg, not in messages.
        """
        system: str | None = None
        user_messages: list[MessageParam] = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                user_messages.append(
                    {"role": m["role"], "content": m["content"]}  # type: ignore[typeddict-item]
                )
        return system, user_messages

    async def complete(self, messages: list[dict[str, str]]) -> str:
        system, typed = self._split_messages(messages)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=system or "",
            messages=typed,
        )
        block = response.content[0]
        if not isinstance(block, TextBlock):
            raise ValueError(f"Unexpected content block type: {type(block)}")
        return block.text

    async def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str, None]:
        system, typed = self._split_messages(messages)
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=system or "",
            messages=typed,
        ) as s:
            async for text in s.text_stream:
                yield text


class OpenAILLMClient:
    """OpenAI LLM client implementing LLMClientProtocol."""

    def __init__(
        self,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 1.0,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        typed = cast(list[ChatCompletionMessageParam], messages)
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=typed,
        )
        return response.choices[0].message.content or ""

    async def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str, None]:
        typed = cast(list[ChatCompletionMessageParam], messages)
        response: AsyncStream[ChatCompletionChunk] = (
            await self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                messages=typed,
                stream=True,
            )
        )
        async for chunk in response:
            content = chunk.choices[0].delta.content
            if content is not None:
                yield content


# --- Factory ---


def get_llm(role: str) -> LLMClientProtocol:
    """Get LLM client for the specified role.

    Resolves provider and model from config/models.yaml based on role.

    Args:
        role: Logical role (e.g., 'orchestrator', 'intent_parser')

    Returns:
        LLM client implementing LLMClientProtocol

    Raises:
        KeyError: If role not found in config
        ValueError: If provider is unsupported
    """
    config: dict[str, Any] = load_yaml_config("models.yaml")
    role_config: dict[str, Any] = config[role]

    provider: str = role_config["provider"]
    model: str = role_config["model"]
    max_tokens: int = role_config.get("max_tokens", 1024)
    temperature: float = role_config.get("temperature", 1.0)

    local: dict[str, Any] = _load_local_config()
    providers_cfg: dict[str, Any] = local.get("providers", {})

    if provider == "anthropic":
        api_key: str | None = providers_cfg.get("anthropic", {}).get("api_key")
        return AnthropicLLMClient(
            model=model, max_tokens=max_tokens, temperature=temperature, api_key=api_key
        )

    if provider == "openai":
        api_key = providers_cfg.get("openai", {}).get("api_key")
        return OpenAILLMClient(
            model=model, max_tokens=max_tokens, temperature=temperature, api_key=api_key
        )

    raise ValueError(f"Unsupported provider: {provider}")
