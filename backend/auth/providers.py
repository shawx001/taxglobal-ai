"""Multi-provider OAuth login registry: Google, Apple, WeChat.

Each provider exposes the same shape — ``configured``, ``build_authorize_url``,
``complete_login`` — so the auth routes are provider-agnostic. Google is fully
implemented (see google.py). Apple and WeChat build the real authorize redirect
and complete login via each platform's documented token/identity endpoints
(HTTP goes through the shared, test-stubbable helpers); they activate only when
their credentials are configured. When a provider is not configured the frontend
falls back to the dev login, so every button is usable in sandbox.

Identity is always taken from the provider's server-to-server token/userinfo
response over HTTPS — never fabricated.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import urllib.parse
from abc import ABC, abstractmethod

from .google import GoogleOAuthError, _http_get_json, _http_post_form, google_oauth
from .sessions import AuthUser

# Reuse Google's error type as the common login error.
AuthProviderError = GoogleOAuthError

APPLE_AUTH_ENDPOINT = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_ENDPOINT = "https://appleid.apple.com/auth/token"  # noqa: S105 - public OAuth URL
WECHAT_AUTH_ENDPOINT = "https://open.weixin.qq.com/connect/qrconnect"
WECHAT_TOKEN_ENDPOINT = "https://api.weixin.qq.com/sns/oauth2/access_token"  # noqa: S105 - public OAuth URL
WECHAT_USERINFO_ENDPOINT = "https://api.weixin.qq.com/sns/userinfo"


class OAuthProvider(ABC):
    name: str = ""

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    def build_authorize_url(self, state: str) -> str: ...

    @abstractmethod
    def complete_login(self, code: str) -> AuthUser: ...


def _decode_jwt_claims(token: str) -> dict:
    """Decode (without verifying) a JWT payload.

    Safe here because the JWT is the id_token returned from the provider's own
    HTTPS token endpoint via our authenticated server-to-server exchange — not a
    value taken from the browser.
    """

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode())
    except (IndexError, ValueError, binascii.Error) as exc:
        raise AuthProviderError(f"could not decode id_token: {exc}") from exc


class AppleOAuth(OAuthProvider):
    """Sign in with Apple. ``client_secret`` is the operator-generated ES256 JWT."""

    name = "apple"

    def __init__(self) -> None:
        self.client_id = os.environ.get("TAXGLOBAL_APPLE_CLIENT_ID", "")
        self.client_secret = os.environ.get("TAXGLOBAL_APPLE_CLIENT_SECRET", "")
        self.redirect_uri = os.environ.get("TAXGLOBAL_APPLE_REDIRECT_URI", "")

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    def build_authorize_url(self, state: str) -> str:
        if not self.configured:
            raise AuthProviderError("Apple OAuth is not configured")
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "name email",
            "response_mode": "form_post",
            "state": state,
        }
        return f"{APPLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

    def complete_login(self, code: str) -> AuthUser:
        if not self.configured:
            raise AuthProviderError("Apple OAuth is not configured")
        if not code:
            raise AuthProviderError("missing authorization code")
        try:
            token_response = _http_post_form(
                APPLE_TOKEN_ENDPOINT,
                {
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        except Exception as exc:
            raise AuthProviderError(f"Apple token exchange failed: {exc}") from exc
        id_token = token_response.get("id_token")
        if not id_token:
            raise AuthProviderError("Apple token response missing id_token")
        claims = _decode_jwt_claims(id_token)
        sub = claims.get("sub")
        email = claims.get("email", "")
        if not sub:
            raise AuthProviderError("Apple id_token missing sub")
        return AuthUser(sub=str(sub), email=str(email), name="", provider="apple")


class WeChatOAuth(OAuthProvider):
    """WeChat Open Platform QR login (网站应用扫码登录)."""

    name = "wechat"

    def __init__(self) -> None:
        self.app_id = os.environ.get("TAXGLOBAL_WECHAT_APP_ID", "")
        self.app_secret = os.environ.get("TAXGLOBAL_WECHAT_APP_SECRET", "")
        self.redirect_uri = os.environ.get("TAXGLOBAL_WECHAT_REDIRECT_URI", "")

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret and self.redirect_uri)

    def build_authorize_url(self, state: str) -> str:
        if not self.configured:
            raise AuthProviderError("WeChat OAuth is not configured")
        params = {
            "appid": self.app_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "snsapi_login",
            "state": state,
        }
        # WeChat requires the #wechat_redirect fragment on the qrconnect URL.
        return f"{WECHAT_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}#wechat_redirect"

    def complete_login(self, code: str) -> AuthUser:
        if not self.configured:
            raise AuthProviderError("WeChat OAuth is not configured")
        if not code:
            raise AuthProviderError("missing authorization code")
        token_params = urllib.parse.urlencode(
            {
                "appid": self.app_id,
                "secret": self.app_secret,
                "code": code,
                "grant_type": "authorization_code",
            }
        )
        try:
            token_response = _http_get_json(f"{WECHAT_TOKEN_ENDPOINT}?{token_params}")
        except Exception as exc:
            raise AuthProviderError(f"WeChat token exchange failed: {exc}") from exc
        access_token = token_response.get("access_token")
        openid = token_response.get("openid")
        if not (access_token and openid):
            raise AuthProviderError("WeChat token response missing access_token/openid")
        info_params = urllib.parse.urlencode({"access_token": access_token, "openid": openid})
        try:
            info = _http_get_json(f"{WECHAT_USERINFO_ENDPOINT}?{info_params}")
        except Exception as exc:
            raise AuthProviderError(f"WeChat userinfo request failed: {exc}") from exc
        # WeChat has no email; identity is the openid, display name the nickname.
        return AuthUser(sub=str(openid), email="", name=str(info.get("nickname") or ""), provider="wechat")


apple_oauth = AppleOAuth()
wechat_oauth = WeChatOAuth()

PROVIDERS: dict[str, OAuthProvider] = {
    "google": google_oauth,
    "apple": apple_oauth,
    "wechat": wechat_oauth,
}


def get_provider(name: str) -> OAuthProvider | None:
    return PROVIDERS.get((name or "").strip().lower())
