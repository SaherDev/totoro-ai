"""LLM provider factory - resolves configured LLM clients by role."""

from collections.abc import AsyncGenerator
from typing import Any, Protocol, cast, runtime_checkable

import anthropic
import instructor
import openai
from anthropic.types import MessageParam, TextBlock
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError

from totoro_ai.core.config import get_config, get_secrets


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


class InstructorClient:
    """Instructor-patched OpenAI client for structured extraction (ADR-020)."""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        """Initialize Instructor client with OpenAI backend.

        Args:
            model: Model name (e.g., 'gpt-4o-mini')
            api_key: OpenAI API key (uses env if None)
        """
        self._model = model
        self._openai_client = openai.AsyncOpenAI(api_key=api_key)
        self._client = instructor.from_openai(self._openai_client)

    async def extract(
        self,
        response_model: type[BaseModel],
        messages: list[dict[str, str]],
        max_retries: int = 3,
    ) -> BaseModel:
        """Extract structured data using the specified response model.

        Args:
            response_model: Pydantic model for structured output
            messages: Chat messages for the LLM
            max_retries: Number of retries on Instructor exceptions

        Returns:
            Extracted data as instance of response_model

        Raises:
            ValidationError: If final output fails schema validation
            RuntimeError: If extraction fails after max retries
        """
        try:
            result = await self._client.chat.completions.create(
                model=self._model,
                response_model=response_model,
                messages=messages,
                max_retries=max_retries,
            )
            return result
        except instructor.IncompleteOutputException as e:
            raise RuntimeError(f"Incomplete extraction: {e}")
        except instructor.InstructorRetryException as e:
            raise RuntimeError(f"Extraction failed after retries: {e}")
        except ValidationError:
            raise


# --- Factory ---


def get_llm(role: str) -> LLMClientProtocol:
    """Get LLM client for the specified role.

    Resolves provider and model from config/app.yaml under the 'models' key.

    Args:
        role: Logical role (e.g., 'orchestrator', 'intent_parser')

    Returns:
        LLM client implementing LLMClientProtocol

    Raises:
        KeyError: If role not found in config
        ValueError: If provider is unsupported
    """
    role_config = get_config().models[role]
    secrets = get_secrets()

    provider = role_config.provider
    model = role_config.model
    max_tokens = role_config.max_tokens
    temperature = role_config.temperature

    if provider == "anthropic":
        return AnthropicLLMClient(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=secrets.providers.anthropic.api_key,
        )

    if provider == "openai":
        return OpenAILLMClient(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=secrets.providers.openai.api_key,
        )

    raise ValueError(f"Unsupported provider: {provider}")


def get_instructor_client(role: str) -> InstructorClient:
    """Get Instructor-patched client for structured extraction.

    Resolves provider and model from config/app.yaml under the 'models' key.
    Currently only supports OpenAI provider.

    Args:
        role: Logical role (e.g., 'intent_parser')

    Returns:
        InstructorClient

    Raises:
        KeyError: If role not found in config
        ValueError: If provider is not OpenAI
    """
    role_config = get_config().models[role]

    if role_config.provider != "openai":
        raise ValueError(f"Instructor only supports OpenAI provider, got: {role_config.provider}")

    return InstructorClient(
        model=role_config.model,
        api_key=get_secrets().providers.openai.api_key,
    )
