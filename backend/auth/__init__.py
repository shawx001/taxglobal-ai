"""Authentication: multi-provider OAuth login + an in-memory session store.

A provider registry (Google / Apple / WeChat) drives the standard OIDC/OAuth
redirect flow (authorize -> callback code -> token exchange -> identity ->
session) behind the provider-agnostic ``/api/auth/{provider}/*`` routes. A
configured provider sends the user to its real consent screen; without
credentials the dev login (sandbox) keeps every button demonstrable. Sessions
are in-memory so login works with PostgreSQL disabled (graceful degradation);
identity always comes from the provider's token/userinfo response, never
fabricated.
"""

from .google import GoogleOAuth, GoogleOAuthError, google_oauth
from .providers import PROVIDERS, AppleOAuth, AuthProviderError, OAuthProvider, WeChatOAuth, get_provider
from .sessions import AuthUser, SessionStore, session_store

__all__ = [
    "PROVIDERS",
    "AppleOAuth",
    "AuthProviderError",
    "AuthUser",
    "GoogleOAuth",
    "GoogleOAuthError",
    "OAuthProvider",
    "SessionStore",
    "WeChatOAuth",
    "get_provider",
    "google_oauth",
    "session_store",
]
