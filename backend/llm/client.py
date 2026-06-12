"""Module-level LLM provider lifecycle."""

from __future__ import annotations

import logging

from backend import config
from backend.llm.provider import LLMProvider, MockProvider, create_provider
from backend.llm.sanitize_pipeline import SanitizedProvider

logger = logging.getLogger("taxglobal.llm")

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"

_provider: LLMProvider | None = None


def init_llm() -> None:
    """Initialize the configured LLM provider once at app startup."""

    global _provider  # noqa: PLW0603

    if _provider is not None:
        return

    if not config.ENABLE_LLM:
        logger.info("LLM disabled (ENABLE_LLM=false)")
        _provider = None
        return

    provider_name = config.LLM_PROVIDER.strip().lower()
    api_key = config.LLM_API_KEY
    model = config.LLM_MODEL

    if provider_name == "mock":
        from backend.llm.usage_tracker import TrackedProvider

        _provider = TrackedProvider(MockProvider())
        logger.info("LLM provider: mock")
        return

    if not api_key:
        logger.warning("LLM_API_KEY not set; LLM disabled")
        _provider = None
        return

    if provider_name == "deepseek":
        base_url = config.LLM_BASE_URL or DEEPSEEK_BASE_URL
        model = model or DEEPSEEK_DEFAULT_MODEL
    elif provider_name == "openai":
        base_url = config.LLM_BASE_URL or None
        model = model or OPENAI_DEFAULT_MODEL
    else:
        base_url = config.LLM_BASE_URL or None
        model = model or OPENAI_DEFAULT_MODEL

    try:
        inner = create_provider(
            provider_name=provider_name,
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=config.LLM_TIMEOUT,
        )
    except Exception:
        logger.exception("LLM provider initialization failed")
        _provider = None
        return

    from backend.llm.usage_tracker import TrackedProvider

    # Order matters: sanitize first (innermost call sees clean messages),
    # track outermost so every call is counted exactly once.
    _provider = TrackedProvider(SanitizedProvider(inner))
    logger.info("LLM provider: %s (model=%s, base_url=%s)", provider_name, model, base_url or "default")


def close_llm() -> None:
    """Clear provider state at app shutdown."""

    global _provider  # noqa: PLW0603
    _provider = None


def get_provider() -> LLMProvider | None:
    """Return the initialized provider, if LLM is enabled and available."""

    return _provider


def is_llm_available() -> bool:
    """Return True when a configured provider is ready for use."""

    return _provider is not None and _provider.is_available()
