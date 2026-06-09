# Codex Prompt: M3.1 — LLM Provider Abstraction Layer

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `backend/config.py` → `backend/audit/sanitizer.py` → `backend/orchestrator/nodes.py` → `backend/orchestrator/graph.py` → `.claude/skills/openaccountants/federal/us-qbi-deduction.md`（Phase 3 cross-reference）

## Task

Build a pluggable LLM provider layer at `backend/llm/` that lets the orchestrator call DeepSeek, OpenAI, or a deterministic mock through a single interface. Include a PII sanitization pipeline so SSN/email never leaves the server. The rest of M3 (intent, response, chat UI) depends on this layer — it must be solid.

**Why:** M2 uses keyword matching for intent and returns raw JSON. M3 needs an LLM to understand natural language queries and generate human-readable responses. This step isolates the LLM dependency behind an abstraction so we can swap providers, test with mocks, and gracefully degrade when `ENABLE_LLM=false`.

## Core Constraints

1. **Backward compatibility**: All existing tests must pass unchanged. `ENABLE_LLM=false` (default) → zero LLM calls, M2 keyword path untouched.
2. **Data sovereignty**: PII sanitization BEFORE any external API call. SSN and email must be masked. Dollar amounts preserved.
3. **Graceful degradation**: If LLM provider errors/times out → log warning, return `None`. Callers decide fallback.
4. **No changes to orchestrator logic yet** — M3.1 only builds the provider layer. M3.2 will wire it into `classify_node`.
5. **OpenAI SDK for everything** — DeepSeek API is 100% OpenAI-compatible. Use `openai` package with `base_url` override.

## File 1: `backend/llm/__init__.py`

Empty `__init__.py` to make `backend/llm` a package.

## File 2: `backend/llm/provider.py`

```python
"""LLM provider abstraction — sync-first, async optional.

All providers implement the same interface: complete() for single responses,
stream() for token-by-token SSE streaming (M3.5 will need this).
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Iterator

logger = logging.getLogger("taxglobal.llm")


@dataclass(frozen=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)  # prompt_tokens, completion_tokens, total_tokens
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
        """Return a single completion. None on error (logged, not raised)."""
        ...

    @abc.abstractmethod
    def stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Yield content tokens for SSE streaming. Empty on error."""
        ...

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Health check — True if provider can accept requests."""
        ...
```

### OpenAICompatibleProvider (handles both DeepSeek and OpenAI)

```python
class OpenAICompatibleProvider(LLMProvider):
    """Provider for any OpenAI-API-compatible service (OpenAI, DeepSeek, etc.)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,  # None = default OpenAI endpoint
        timeout: float = 30.0,
        provider_name: str = "openai",
    ) -> None:
        # Lazy import — openai is optional dependency
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._model = model
        self._provider_name = provider_name

    def complete(self, messages, *, temperature=0.0, max_tokens=1024, **kwargs):
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            choice = response.choices[0]
            usage = {}
            if response.usage:
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

    def stream(self, messages, *, temperature=0.0, max_tokens=1024, **kwargs):
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **kwargs,
            )
            for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except Exception:
            logger.exception("LLM %s stream failed", self._provider_name)
            return

    def is_available(self) -> bool:
        return self._client is not None
```

### MockProvider (for tests)

```python
class MockProvider(LLMProvider):
    """Deterministic mock for testing. Returns canned responses."""

    def __init__(self, default_response: str = "Mock LLM response.") -> None:
        self._default = default_response
        self._responses: list[str] = []  # queue of responses; pop from front

    def enqueue(self, response: str) -> None:
        """Push a canned response onto the queue."""
        self._responses.append(response)

    def complete(self, messages, **kwargs):
        content = self._responses.pop(0) if self._responses else self._default
        return LLMResponse(
            content=content,
            model="mock",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            finish_reason="stop",
        )

    def stream(self, messages, **kwargs):
        content = self._responses.pop(0) if self._responses else self._default
        for word in content.split():
            yield word + " "

    def is_available(self) -> bool:
        return True
```

### Factory function

```python
def create_provider(
    *,
    provider_name: str,
    api_key: str,
    model: str,
    base_url: str | None = None,
    timeout: float = 30.0,
) -> LLMProvider:
    """Create the right provider based on name."""
    if provider_name == "mock":
        return MockProvider()
    # Both "deepseek" and "openai" use the same OpenAI-compatible client
    return OpenAICompatibleProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout=timeout,
        provider_name=provider_name,
    )
```

## File 3: `backend/llm/sanitize_pipeline.py`

```python
"""PII sanitization for LLM message content.

Sanitizes BEFORE sending to external LLM API. Preserves dollar amounts.
Reuses _mask_ssn() from backend.audit.sanitizer — do NOT duplicate SSN logic.
"""
from __future__ import annotations

import re

from backend.audit.sanitizer import _mask_ssn  # Reuse existing SSN masking (dashed + labeled-undashed)
from backend.llm.provider import LLMMessage, LLMProvider, LLMResponse

_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")


def sanitize_text(text: str) -> str:
    """Mask SSN and email in free text. Preserve dollar amounts.

    SSN masking delegates to backend.audit.sanitizer._mask_ssn() which handles:
    - Dashed SSN: 123-45-6789 → ***-**-6789
    - Labeled undashed SSN: "SSN: 123456789" → "SSN: ***-**-6789"
    """
    result = _mask_ssn(text)  # handles both SSN patterns
    result = _EMAIL_PATTERN.sub("[email redacted]", result)
    return result


def sanitize_messages(messages: list[LLMMessage]) -> list[LLMMessage]:
    """Return new message list with PII masked in content."""
    return [LLMMessage(role=m.role, content=sanitize_text(m.content)) for m in messages]


class SanitizedProvider(LLMProvider):
    """Wraps another provider with PII sanitization on all outgoing messages."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner

    def complete(self, messages, **kwargs) -> LLMResponse | None:
        return self._inner.complete(sanitize_messages(messages), **kwargs)

    def stream(self, messages, **kwargs):
        yield from self._inner.stream(sanitize_messages(messages), **kwargs)

    def is_available(self) -> bool:
        return self._inner.is_available()
```

## File 4: `backend/llm/client.py`

```python
"""Module-level LLM client singleton — initialized once at startup."""
from __future__ import annotations

import logging
from typing import Any

from backend import config
from backend.llm.provider import LLMProvider, MockProvider, create_provider
from backend.llm.sanitize_pipeline import SanitizedProvider

logger = logging.getLogger("taxglobal.llm")

_provider: LLMProvider | None = None


# DeepSeek model defaults
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"  # V4 Flash

# OpenAI fallback defaults
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


def init_llm() -> None:
    """Initialize the LLM provider based on config. Called once at app startup."""
    global _provider  # noqa: PLW0603

    if not config.ENABLE_LLM:
        logger.info("LLM disabled (ENABLE_LLM=false)")
        _provider = None
        return

    provider_name = config.LLM_PROVIDER
    api_key = config.LLM_API_KEY
    model = config.LLM_MODEL

    if not api_key:
        logger.warning("LLM_API_KEY not set; LLM disabled")
        _provider = None
        return

    if provider_name == "mock":
        _provider = MockProvider()
        logger.info("LLM provider: mock")
        return

    # Resolve base_url and model defaults
    if provider_name == "deepseek":
        base_url = config.LLM_BASE_URL or DEEPSEEK_BASE_URL
        model = model or DEEPSEEK_DEFAULT_MODEL
    elif provider_name == "openai":
        base_url = config.LLM_BASE_URL or None  # None = default OpenAI
        model = model or OPENAI_DEFAULT_MODEL
    else:
        base_url = config.LLM_BASE_URL or None
        model = model or "gpt-4o-mini"

    inner = create_provider(
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout=config.LLM_TIMEOUT,
    )
    # Wrap with PII sanitization — all outgoing messages are scrubbed
    _provider = SanitizedProvider(inner)
    logger.info("LLM provider: %s (model=%s, base_url=%s)", provider_name, model, base_url or "default")


def close_llm() -> None:
    """Clean up provider resources."""
    global _provider  # noqa: PLW0603
    _provider = None


def get_provider() -> LLMProvider | None:
    """Return the initialized provider, or None if LLM is disabled."""
    return _provider


def is_llm_available() -> bool:
    """True if an LLM provider is initialized and reporting available."""
    return _provider is not None and _provider.is_available()
```

## File 5: `backend/config.py` — ADD these config entries

Append to the existing config.py (do NOT replace existing content):

```python
# === M3: LLM Provider ===
ENABLE_LLM: bool = _env_bool("ENABLE_LLM", False)  # Default OFF — opt-in
LLM_PROVIDER: str = _env("TAXGLOBAL_LLM_PROVIDER", "deepseek")
LLM_API_KEY: str = _env("TAXGLOBAL_LLM_API_KEY", "")
LLM_MODEL: str = _env("TAXGLOBAL_LLM_MODEL", "")  # Empty = use provider default
LLM_BASE_URL: str = _env("TAXGLOBAL_LLM_BASE_URL", "")
LLM_TIMEOUT: float = float(_env("TAXGLOBAL_LLM_TIMEOUT", "30"))
LLM_FAILOVER_PROVIDER: str = _env("TAXGLOBAL_LLM_FAILOVER_PROVIDER", "openai")
LLM_FAILOVER_API_KEY: str = _env("TAXGLOBAL_LLM_FAILOVER_API_KEY", "")
LLM_FAILOVER_MODEL: str = _env("TAXGLOBAL_LLM_FAILOVER_MODEL", "gpt-4o-mini")
```

**Important: `ENABLE_LLM` defaults to `False`.** Existing tests see no LLM.

## File 6: `backend/main.py` — ADD LLM lifecycle

Add to the existing `lifespan()` context manager:

```python
# In startup section (after init_embedder()):
from backend.llm.client import init_llm, close_llm
init_llm()

# In shutdown section (before close_embedder()):
close_llm()
```

Add to the `/api/health` response `stores` dict:

```python
"llm": is_llm_available(),
```

Import `is_llm_available` from `backend.llm.client`.

## File 7: `backend/requirements.txt` — ADD

```
# === M3: LLM Provider ===
openai>=1.82.0,<2.0
tiktoken>=0.9.0,<1.0
```

## Tests: `tests/test_llm_provider.py`

```python
"""Tests for M3.1 LLM provider abstraction."""

import unittest
from backend.llm.provider import LLMMessage, LLMResponse, MockProvider, create_provider
from backend.llm.sanitize_pipeline import sanitize_text, sanitize_messages, SanitizedProvider


class TestMockProvider(unittest.TestCase):
    def test_complete_default(self):
        mock = MockProvider(default_response="Hello!")
        resp = mock.complete([LLMMessage(role="user", content="Hi")])
        self.assertIsNotNone(resp)
        self.assertEqual(resp.content, "Hello!")
        self.assertEqual(resp.model, "mock")

    def test_complete_queued(self):
        mock = MockProvider()
        mock.enqueue("First")
        mock.enqueue("Second")
        self.assertEqual(mock.complete([]).content, "First")
        self.assertEqual(mock.complete([]).content, "Second")
        # Falls back to default after queue empty
        self.assertEqual(mock.complete([]).content, "Mock LLM response.")

    def test_stream(self):
        mock = MockProvider(default_response="word1 word2 word3")
        tokens = list(mock.stream([LLMMessage(role="user", content="test")]))
        self.assertEqual(len(tokens), 3)
        self.assertIn("word1", tokens[0])

    def test_is_available(self):
        self.assertTrue(MockProvider().is_available())


class TestSanitizeText(unittest.TestCase):
    def test_ssn_masked(self):
        text = "My SSN is 123-45-6789 and I earned $150,000."
        result = sanitize_text(text)
        self.assertIn("***-**-6789", result)
        self.assertNotIn("123-45", result)
        self.assertIn("$150,000", result)  # Dollar amount preserved

    def test_labeled_ssn_masked(self):
        text = "SSN: 123456789"
        result = sanitize_text(text)
        self.assertIn("***-**-6789", result)
        self.assertNotIn("123456789", result)

    def test_email_masked(self):
        text = "Contact me at john.doe@example.com for details."
        result = sanitize_text(text)
        self.assertIn("[email redacted]", result)
        self.assertNotIn("john.doe@example.com", result)

    def test_no_pii_unchanged(self):
        text = "What is the standard deduction for 2025?"
        self.assertEqual(sanitize_text(text), text)

    def test_dollar_amounts_preserved(self):
        text = "I made $200,000 in California with SSN 123-45-6789."
        result = sanitize_text(text)
        self.assertIn("$200,000", result)
        self.assertNotIn("123-45-6789", result)


class TestSanitizedProvider(unittest.TestCase):
    def test_sanitizes_before_sending(self):
        """PII must be stripped from messages before reaching the inner provider."""
        captured = []
        class SpyProvider(MockProvider):
            def complete(self, messages, **kwargs):
                captured.extend(messages)
                return super().complete(messages, **kwargs)

        inner = SpyProvider()
        provider = SanitizedProvider(inner)
        provider.complete([LLMMessage(role="user", content="SSN is 123-45-6789")])
        self.assertTrue(len(captured) > 0)
        self.assertNotIn("123-45-6789", captured[0].content)
        self.assertIn("***-**-6789", captured[0].content)


class TestCreateProvider(unittest.TestCase):
    def test_mock_provider(self):
        p = create_provider(provider_name="mock", api_key="", model="")
        self.assertIsInstance(p, MockProvider)

    # NOTE: DeepSeek/OpenAI providers require API keys and network.
    # Integration tests for those should be in a separate file with
    # @unittest.skipUnless(os.environ.get("TAXGLOBAL_LLM_API_KEY"), "No API key")


class TestClientModule(unittest.TestCase):
    """Test the init/close lifecycle with ENABLE_LLM=false."""

    def test_disabled_by_default(self):
        from backend.llm import client
        # Save original
        import backend.config as cfg
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = False
            client.init_llm()
            self.assertIsNone(client.get_provider())
            self.assertFalse(client.is_llm_available())
            client.close_llm()
        finally:
            cfg.ENABLE_LLM = original

    def test_mock_provider_via_config(self):
        from backend.llm import client
        import backend.config as cfg
        originals = (cfg.ENABLE_LLM, cfg.LLM_PROVIDER, cfg.LLM_API_KEY)
        try:
            cfg.ENABLE_LLM = True
            cfg.LLM_PROVIDER = "mock"
            cfg.LLM_API_KEY = "test"
            client.init_llm()
            self.assertTrue(client.is_llm_available())
            provider = client.get_provider()
            resp = provider.complete([LLMMessage(role="user", content="test")])
            self.assertIsNotNone(resp)
            client.close_llm()
        finally:
            cfg.ENABLE_LLM, cfg.LLM_PROVIDER, cfg.LLM_API_KEY = originals
```

## Acceptance Gates

```powershell
# 1. All existing tests still pass (ENABLE_LLM defaults to false)
python -m unittest discover -s tests

# 2. Lint
python -m ruff check engine backend tests scripts

# 3. Health endpoint shows llm: false when disabled
# (manual or add assertion in existing health test)

# 4. New tests pass
python -m unittest tests.test_llm_provider -v

# 5. Verify config defaults
python -c "from backend import config; assert config.ENABLE_LLM is False; print('ENABLE_LLM default OK')"
```

## Commit Format

```
feat(llm): add M3.1 LLM provider abstraction layer

Introduce backend/llm/ package with pluggable provider interface
(DeepSeek, OpenAI, Mock), PII sanitization pipeline (SSN/email
masked before external API calls), and ENABLE_LLM feature flag
(default off — zero impact on existing M2 keyword path).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

## Notes for Codex

- **Do NOT modify** `backend/orchestrator/` — M3.2 will wire LLM into classify_node.
- `backend/main.py`: only add `init_llm()`/`close_llm()` to lifespan and `llm` to health. Do not restructure.
- `backend/config.py`: only APPEND new config entries. Do not modify existing entries.
- `openai` package is the **only** new dependency for LLM calls. DeepSeek uses the same SDK.
- `tiktoken` is added now for M3.7 token counting; not used in M3.1 but pinned early.
- The `SanitizedProvider` is a decorator pattern — it wraps any `LLMProvider` transparently.
- **No failover logic in M3.1.** Failover config is defined but the actual failover chain (try DeepSeek → fallback to OpenAI) will be added in M3.2 or later when we have real usage patterns.
- Keep `backend/llm/` under 400 total lines across all files.
