"""M3.7: in-process LLM usage + cost tracking.

Aggregates per-day, per-model token usage and a USD cost estimate from
every provider call. In-memory only — counters reset on process restart
(persistence is a later step; the admin endpoint says so explicitly).
No query/answer content is ever recorded — counts and totals only.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from backend import config
from backend.llm.provider import LLMMessage, LLMProvider, LLMResponse


def _parse_price(raw: str, default: str) -> Decimal:
    """A typo in a cost-display env var must never crash the tax engine."""

    try:
        value = Decimal(raw)
    except Exception:
        return Decimal(default)
    if not value.is_finite() or value < 0:
        return Decimal(default)
    return value


# USD per 1M tokens; env-overridable so price changes never need code edits.
_PRICE_INPUT_PER_MTOK = _parse_price(config.LLM_PRICE_INPUT_MTOK, "0.14")
_PRICE_OUTPUT_PER_MTOK = _parse_price(config.LLM_PRICE_OUTPUT_MTOK, "0.28")
_MTOK = Decimal("1000000")

_lock = threading.Lock()
_usage: dict[str, dict[str, dict[str, Any]]] = {}
_started_at = ""


def record_usage(model: str, usage: dict[str, int]) -> None:
    """Add one call's token usage to the aggregate. Never raises."""

    global _started_at  # noqa: PLW0603
    try:
        prompt = max(0, int(usage.get("prompt_tokens", 0)))
        completion = max(0, int(usage.get("completion_tokens", 0)))
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        with _lock:
            if not _started_at:
                _started_at = datetime.now(UTC).isoformat()
            bucket = _usage.setdefault(day, {}).setdefault(
                model or "unknown",
                {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0},
            )
            bucket["calls"] += 1
            bucket["prompt_tokens"] += prompt
            bucket["completion_tokens"] += completion
    except Exception:
        pass


def usage_summary() -> dict[str, Any]:
    """Aggregated usage with USD cost estimates."""

    with _lock:
        days: dict[str, Any] = {}
        total_cost = Decimal("0")
        total_calls = 0
        for day, models in _usage.items():
            day_out = {}
            for model, bucket in models.items():
                cost = (
                    Decimal(bucket["prompt_tokens"]) * _PRICE_INPUT_PER_MTOK
                    + Decimal(bucket["completion_tokens"]) * _PRICE_OUTPUT_PER_MTOK
                ) / _MTOK
                total_cost += cost
                total_calls += bucket["calls"]
                day_out[model] = {**bucket, "estimated_cost_usd": float(round(cost, 4))}
            days[day] = day_out
        return {
            "since": _started_at,
            "persistence": "in_memory_per_worker_resets_on_restart",
            "total_calls": total_calls,
            "estimated_total_cost_usd": float(round(total_cost, 4)),
            "days": days,
        }


def reset_usage() -> None:
    """Clear counters (tests + process shutdown)."""

    global _started_at  # noqa: PLW0603
    with _lock:
        _usage.clear()
        _started_at = ""


class TrackedProvider(LLMProvider):
    """Decorator recording usage for every completion call."""

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
        response = self._inner.complete(messages, temperature=temperature, max_tokens=max_tokens, **kwargs)
        if response is not None and isinstance(response.usage, dict):
            record_usage(response.model, response.usage)
        return response

    def stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Iterator[str]:
        # Plain function returning the inner iterator — the call is counted
        # at CALL time, not first iteration. Streamed responses carry no
        # usage object, so only the call is recorded.
        record_usage(getattr(self._inner, "_model", None) or "stream", {})
        return self._inner.stream(messages, temperature=temperature, max_tokens=max_tokens, **kwargs)

    def is_available(self) -> bool:
        return self._inner.is_available()
