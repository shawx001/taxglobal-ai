"""Auth routes: multi-provider OAuth login, dev login, session check, logout.

Provider-agnostic: ``/api/auth/{provider}/login`` and ``/callback`` work for
google / apple / wechat via the provider registry. The session token rides an
httponly, SameSite=Lax cookie so client JS can never read it. The OAuth
``state`` is single-use and server-validated for CSRF. A configured provider
drives its real consent screen; otherwise the dev login (gated by
``TAXGLOBAL_ENABLE_DEV_LOGIN``) keeps every button demonstrable in sandbox.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.errors import error_response

from .providers import AuthProviderError, get_provider
from .sessions import AuthUser, now_seconds, session_store, state_store

router = APIRouter()

SESSION_COOKIE = "tg_session"


class DevLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=200)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _error(request: Request, *, status_code: int, code: str, message: str, details: list | None = None) -> JSONResponse:
    rid = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        headers={"X-Request-ID": rid},
        content=error_response(code=code, message=message, request_id=rid, details=details),
    )


def _dev_login_enabled() -> bool:
    # Disabled by default: an enabled dev login lets anyone forge a session with
    # any email and bypass Google. Operators must opt in explicitly (and only in
    # trusted/dev environments).
    return os.environ.get("TAXGLOBAL_ENABLE_DEV_LOGIN", "false").strip().lower() in {"1", "true", "yes"}


def _cookie_secure() -> bool:
    return os.environ.get("TAXGLOBAL_SESSION_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"}


def _post_login_redirect() -> str:
    return os.environ.get("TAXGLOBAL_POST_LOGIN_REDIRECT", "/")


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        path="/",
    )


@router.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, object]:
    user = session_store.get(request.cookies.get(SESSION_COOKIE))
    if user is None:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": user.as_dict()}


@router.get("/api/auth/{provider}/login")
def provider_login(provider: str, request: Request) -> Response:
    oauth = get_provider(provider)
    if oauth is None:
        return _error(
            request, status_code=404, code="unknown_provider", message=f"Unknown login provider '{provider}'."
        )
    if not oauth.configured:
        return _error(
            request,
            status_code=503,
            code="provider_not_configured",
            message=f"{provider} OAuth is not configured; use POST /api/auth/dev-login in sandbox.",
            details=[{"provider": provider, "dev_login_enabled": _dev_login_enabled()}],
        )
    state = state_store.issue(now=now_seconds())
    return RedirectResponse(url=oauth.build_authorize_url(state), status_code=302)


@router.get("/api/auth/{provider}/callback")
def provider_callback(provider: str, request: Request, code: str = "", state: str = "") -> Response:
    oauth = get_provider(provider)
    if oauth is None:
        return _error(
            request, status_code=404, code="unknown_provider", message=f"Unknown login provider '{provider}'."
        )
    if not state_store.consume(state, now=now_seconds()):
        return _error(
            request, status_code=400, code="invalid_state", message="OAuth state is missing, expired, or reused."
        )
    try:
        user = oauth.complete_login(code)
    except AuthProviderError as exc:
        return _error(request, status_code=400, code="login_failed", message=str(exc))
    token = session_store.create(user)
    response = RedirectResponse(url=_post_login_redirect(), status_code=302)
    _set_session_cookie(response, token)
    return response


@router.post("/api/auth/dev-login", response_model=None)
def dev_login(payload: DevLoginRequest, request: Request, response: Response) -> Response | dict[str, object]:
    if not _dev_login_enabled():
        return _error(
            request,
            status_code=403,
            code="dev_login_disabled",
            message="Dev login is disabled; set TAXGLOBAL_ENABLE_DEV_LOGIN=true in a trusted environment.",
        )
    user = AuthUser(sub=f"dev:{payload.email}", email=payload.email, name=payload.name, provider="dev")
    token = session_store.create(user)
    _set_session_cookie(response, token)
    return {"authenticated": True, "user": user.as_dict()}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, object]:
    session_store.delete(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"authenticated": False}
