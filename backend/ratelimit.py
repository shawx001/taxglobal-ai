"""M3.8: per-client sliding-window rate limiting for LLM-backed endpoints.

One assistant message fans out to several LLM calls (rewrite + classify +
extract + response + retry), and W-2 extraction hits a paid vision model,
so an unthrottled caller can burn the API budget. This middleware caps
requests per client over a sliding window.

In-memory and per-worker (like usage_tracker) — adequate for a single-
process MVP; a shared store (Redis) is the multi-worker upgrade path.
Disabled by default (TAXGLOBAL_ENABLE_RATE_LIMIT); production turns it on.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend import config
from backend.errors import error_response

# Sweep stale per-client deques when the table grows past this many clients,
# so memory stays bounded under churning/spoofed client ids.
_SWEEP_THRESHOLD = 4096


class SlidingWindowLimiter:
    """Thread-safe per-client sliding-window counter."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client_id: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            if len(self._hits) > _SWEEP_THRESHOLD:
                self._sweep(cutoff)
            hits = self._hits[client_id]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self._max:
                return False
            hits.append(now)
            return True

    def _sweep(self, cutoff: float) -> None:
        # Caller holds the lock. Drop clients whose hits are all expired.
        for client_id in list(self._hits):
            hits = self._hits[client_id]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                del self._hits[client_id]


# Per-path-group limiters, lazily built from config so env overrides apply.
_limiters: dict[str, SlidingWindowLimiter] = {}
_limiters_lock = threading.Lock()


def _limiter(group: str, max_requests: int) -> SlidingWindowLimiter:
    with _limiters_lock:
        limiter = _limiters.get(group)
        if limiter is None:
            limiter = SlidingWindowLimiter(max_requests, config.RATE_LIMIT_WINDOW_S)
            _limiters[group] = limiter
        return limiter


def reset_limiters() -> None:
    """Clear limiter state (tests)."""

    with _limiters_lock:
        _limiters.clear()


def _client_id(scope: Scope) -> str:
    """Best-effort client identity. X-Forwarded-For (first hop) when behind a
    proxy, else the socket peer. Spoofable at the app layer — a real edge/WAF
    limit should sit in front; this is defence in depth for the API budget."""

    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            first = value.decode("latin-1").split(",")[0].strip()
            if first:
                return first
    client = scope.get("client")
    return client[0] if client else "unknown"


def _group_for_path(path: str) -> tuple[str, int] | None:
    if path.startswith("/api/assistant/"):
        return "assistant", config.RATE_LIMIT_ASSISTANT
    if path.startswith("/api/documents/"):
        return "documents", config.RATE_LIMIT_DOCUMENTS
    return None


class RateLimitMiddleware:
    """ASGI middleware throttling LLM-backed endpoints per client."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not config.ENABLE_RATE_LIMIT:
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        group = _group_for_path(str(scope.get("path", "")))
        # Only throttle the mutating calls that cost LLM tokens; let CORS
        # preflight through.
        if group is None or method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        group_name, limit = group
        if _limiter(group_name, limit).allow(_client_id(scope)):
            await self.app(scope, receive, send)
            return

        state = scope.get("state") or {}
        request_id = str(state.get("request_id", "unknown"))
        response = JSONResponse(
            status_code=429,
            content=error_response(
                code="rate_limited",
                message="Too many requests. Please slow down and retry shortly.",
                request_id=request_id,
            ),
            headers={"Retry-After": str(config.RATE_LIMIT_WINDOW_S)},
        )
        await response(scope, receive, send)
