"""LLM provider abstraction layer."""

from __future__ import annotations

import abc
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("taxglobal.llm")


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """Abstract base for LLM providers."""

    @abc.abstractmethod
    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse | None:
        """Return a single completion, or None on provider failure."""

    @abc.abstractmethod
    def stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Yield content tokens for streaming responses."""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True when the provider can accept requests."""


class OpenAICompatibleProvider(LLMProvider):
    """Provider for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout: float = 30.0,
        provider_name: str = "openai",
    ) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._model = model
        self._provider_name = provider_name

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse | None:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": message.role, "content": message.content} for message in messages],
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            choice = response.choices[0]
            usage = {}
            if response.usage is not None:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                usage=usage,
                finish_reason=choice.finish_reason or "",
                raw=response.model_dump(),
            )
        except Exception:
            logger.exception("LLM %s completion failed", self._provider_name)
            return None

    def stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Iterator[str]:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": message.role, "content": message.content} for message in messages],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **kwargs,
            )
            for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is not None and delta.content:
                    yield delta.content
        except Exception:
            logger.exception("LLM %s stream failed", self._provider_name)
            return

    def is_available(self) -> bool:
        return self._client is not None


class MockProvider(LLMProvider):
    """Deterministic provider for tests and disabled-network development."""

    def __init__(self, default_response: str = "Mock LLM response.") -> None:
        self._default = default_response
        self._responses: list[str] = []

    def enqueue(self, response: str) -> None:
        self._responses.append(response)

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse | None:
        _ = (messages, temperature, max_tokens, kwargs)
        content = self._responses.pop(0) if self._responses else self._default
        return LLMResponse(
            content=content,
            model="mock",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            finish_reason="stop",
        )

    def stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Iterator[str]:
        _ = (messages, temperature, max_tokens, kwargs)
        content = self._responses.pop(0) if self._responses else self._default
        for word in content.split():
            yield word + " "

    def is_available(self) -> bool:
        return True


def create_provider(
    *,
    provider_name: str,
    api_key: str,
    model: str,
    base_url: str | None = None,
    timeout: float = 30.0,
) -> LLMProvider:
    """Create an LLM provider by name."""

    if provider_name == "mock":
        return MockProvider()
    return OpenAICompatibleProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout=timeout,
        provider_name=provider_name,
    )
