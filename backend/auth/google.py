"""Google OAuth (OIDC) login.

A configured client builds the real Google authorize URL and completes login by
exchanging the code for tokens and reading Google's userinfo endpoint over HTTPS
(so we never have to verify the ID-token JWT ourselves). HTTP goes through two
small module functions so tests can stub them; with no credentials the flow
fails loudly and callers fall back to the dev login.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from .sessions import AuthUser

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - public OAuth URL, not a secret
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
DEFAULT_SCOPES = ("openid", "email", "profile")
_HTTP_TIMEOUT = 10


class GoogleOAuthError(Exception):
    """Login could not be completed."""


def _http_post_form(url: str, data: dict[str, str]) -> dict[str, Any]:  # pragma: no cover - network
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(url, data=body, method="POST")  # noqa: S310 - fixed https Google endpoint
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:  # noqa: S310
        return json.loads(response.read().decode())


def _http_get_json(url: str, *, bearer: str) -> dict[str, Any]:  # pragma: no cover - network
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:  # noqa: S310
        return json.loads(response.read().decode())


class GoogleOAuth:
    """Google OAuth client driven by environment configuration."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
    ) -> None:
        self.client_id = client_id if client_id is not None else os.environ.get("TAXGLOBAL_GOOGLE_CLIENT_ID", "")
        self.client_secret = (
            client_secret if client_secret is not None else os.environ.get("TAXGLOBAL_GOOGLE_CLIENT_SECRET", "")
        )
        self.redirect_uri = (
            redirect_uri if redirect_uri is not None else os.environ.get("TAXGLOBAL_GOOGLE_REDIRECT_URI", "")
        )

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    def build_authorize_url(self, state: str) -> str:
        if not self.configured:
            raise GoogleOAuthError(
                "Google OAuth is not configured; set the env vars TAXGLOBAL_GOOGLE_CLIENT_ID, "
                "TAXGLOBAL_GOOGLE_CLIENT_SECRET and TAXGLOBAL_GOOGLE_REDIRECT_URI"
            )
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(DEFAULT_SCOPES),
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

    def complete_login(self, code: str) -> AuthUser:
        """Exchange the authorization code and read Google's userinfo."""

        if not self.configured:
            raise GoogleOAuthError("Google OAuth is not configured")
        if not code:
            raise GoogleOAuthError("missing authorization code")
        try:
            token_response = _http_post_form(
                GOOGLE_TOKEN_ENDPOINT,
                {
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        except Exception as exc:  # network / non-JSON / HTTP error -> clean login failure
            raise GoogleOAuthError(f"token exchange request failed: {exc}") from exc
        access_token = token_response.get("access_token")
        if not access_token:
            raise GoogleOAuthError("token exchange did not return an access_token")
        try:
            info = _http_get_json(GOOGLE_USERINFO_ENDPOINT, bearer=access_token)
        except Exception as exc:
            raise GoogleOAuthError(f"userinfo request failed: {exc}") from exc
        sub = info.get("sub")
        email = info.get("email")
        if not (sub and email):
            raise GoogleOAuthError("userinfo missing sub/email")
        # Reject an explicitly unverified email; tolerate the field being absent.
        if info.get("email_verified") is False:
            raise GoogleOAuthError("Google reports this email as not verified")
        return AuthUser(sub=str(sub), email=str(email), name=str(info.get("name") or ""), provider="google")


google_oauth = GoogleOAuth()
