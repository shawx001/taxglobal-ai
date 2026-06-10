"""PII sanitization for outgoing LLM messages."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from backend.audit.sanitizer import _mask_ssn
from backend.llm.provider import LLMMessage, LLMProvider, LLMResponse

_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Bare 9-digit sequences are masked as potential SSNs, EXCEPT when they are
# clearly part of a decimal number: followed by ".<digit>" (an amount like
# 123456789.00) or preceded by "." (fraction digits like 0.123456789).
# Engine amounts are floats quantized to cents, so JSON always serializes
# them with a decimal point (e.g. 123456789.0) and they are never masked.
_BARE_NINE_DIGIT_PATTERN = re.compile(r"(?<![\d.])(\d{9})(?!\.?\d)")


def sanitize_text(text: str) -> str:
    """Mask SSN and email in free text while preserving dollar amounts."""

    result = _mask_ssn(text)
    result = _BARE_NINE_DIGIT_PATTERN.sub(_mask_bare_ssn, result)
    return _EMAIL_PATTERN.sub("[email redacted]", result)


def _mask_bare_ssn(match: re.Match[str]) -> str:
    prefix = match.string[: match.start()].rstrip()
    if prefix.endswith("$"):
        return match.group(1)
    return f"***-**-{match.group(1)[-4:]}"


def sanitize_messages(messages: list[LLMMessage]) -> list[LLMMessage]:
    """Return a new message list with PII masked in each content field."""

    return [LLMMessage(role=message.role, content=sanitize_text(message.content)) for message in messages]


def sanitize_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return provider kwargs with free-text PII sanitized.

    OpenAI-compatible kwargs contain protocol keys such as function/schema
    ``name`` fields.  We sanitize string values recursively, but avoid
    key-based redaction so request schemas remain intact.
    """

    return _sanitize_any(kwargs)


def _sanitize_any(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_any(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_any(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_any(item) for item in value)
    if isinstance(value, str):
        return sanitize_text(value)
    return value


class SanitizedProvider(LLMProvider):
    """Decorator that sanitizes all messages before delegating to a provider."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse | None:
        safe_kwargs = sanitize_kwargs(kwargs)
        return self._inner.complete(
            sanitize_messages(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            **safe_kwargs,
        )

    def stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Iterator[str]:
        safe_kwargs = sanitize_kwargs(kwargs)
        yield from self._inner.stream(
            sanitize_messages(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            **safe_kwargs,
        )

    def is_available(self) -> bool:
        return self._inner.is_available()
