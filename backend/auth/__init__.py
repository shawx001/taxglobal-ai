"""Authentication: real Google OAuth login + an in-memory session store.

Login follows the standard OIDC redirect flow (authorize -> callback code ->
token exchange -> Google userinfo -> session). A configured GOOGLE_CLIENT_ID
sends the user to Google's real consent screen; without credentials the dev
login (sandbox) keeps the flow demonstrable. Sessions are in-memory so login
works with PostgreSQL disabled (graceful degradation); identity comes from
Google's verified userinfo, never fabricated.
"""

from .google import GoogleOAuth, GoogleOAuthError, google_oauth
from .sessions import AuthUser, SessionStore, session_store

__all__ = [
    "AuthUser",
    "GoogleOAuth",
    "GoogleOAuthError",
    "SessionStore",
    "google_oauth",
    "session_store",
]
