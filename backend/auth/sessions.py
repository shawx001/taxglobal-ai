"""In-memory session + OAuth-state stores (no database required).

Tokens are cryptographically random opaque strings; the session holds only the
authenticated user's identity (sub/email/name), never any secret. The state
store backs CSRF protection for the OAuth redirect and expires entries.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

DEFAULT_STATE_TTL_SECONDS = 600  # OAuth round-trip should complete quickly
DEFAULT_SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days


@dataclass(frozen=True)
class AuthUser:
    """An authenticated identity (from Google userinfo or a dev login)."""

    sub: str
    email: str
    name: str = ""
    provider: str = "google"

    def as_dict(self) -> dict[str, str]:
        return {"sub": self.sub, "email": self.email, "name": self.name, "provider": self.provider}


class SessionStore:
    """Thread-safe in-memory session table keyed by an opaque token.

    Sessions carry a TTL and are pruned on access so the store cannot grow
    without bound or hand out stale sessions in a long-running process.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS) -> None:
        self._sessions: dict[str, tuple[AuthUser, float]] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def create(self, user: AuthUser, *, now: float | None = None) -> str:
        ts = now_seconds() if now is None else now
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune(ts)
            self._sessions[token] = (user, ts + self._ttl)
        return token

    def get(self, token: str | None, *, now: float | None = None) -> AuthUser | None:
        if not token:
            return None
        ts = now_seconds() if now is None else now
        with self._lock:
            entry = self._sessions.get(token)
            if entry is None:
                return None
            user, expiry = entry
            if expiry < ts:
                self._sessions.pop(token, None)
                return None
            return user

    def delete(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _prune(self, now: float) -> None:
        expired = [token for token, (_user, expiry) in self._sessions.items() if expiry < now]
        for token in expired:
            self._sessions.pop(token, None)


class StateStore:
    """Short-lived OAuth ``state`` values for CSRF protection."""

    def __init__(self, ttl_seconds: int = DEFAULT_STATE_TTL_SECONDS) -> None:
        self._states: dict[str, float] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def issue(self, *, now: float) -> str:
        state = secrets.token_urlsafe(24)
        with self._lock:
            self._prune(now)
            self._states[state] = now + self._ttl
        return state

    def consume(self, state: str | None, *, now: float) -> bool:
        """Validate and single-use-consume a state; False if unknown/expired."""

        if not state:
            return False
        with self._lock:
            self._prune(now)
            expiry = self._states.pop(state, None)
        return expiry is not None and expiry >= now

    def _prune(self, now: float) -> None:
        expired = [state for state, expiry in self._states.items() if expiry < now]
        for state in expired:
            self._states.pop(state, None)


def now_seconds() -> float:
    return time.time()


session_store = SessionStore()
state_store = StateStore()
