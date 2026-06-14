"""Tests for the Google OAuth login + session subsystem (no network/DB)."""

from __future__ import annotations

import unittest
from unittest import mock

from starlette.testclient import TestClient

import backend.auth.routes as auth_routes
from backend.auth import google as google_mod
from backend.auth.google import GoogleOAuth, GoogleOAuthError
from backend.auth.sessions import AuthUser, SessionStore, StateStore, session_store, state_store
from backend.main import app


class SessionStoreTests(unittest.TestCase):
    def test_create_get_delete(self):
        store = SessionStore()
        user = AuthUser(sub="s1", email="a@b.com", name="A")
        token = store.create(user)
        self.assertEqual(store.get(token), user)
        store.delete(token)
        self.assertIsNone(store.get(token))

    def test_get_none_token(self):
        self.assertIsNone(SessionStore().get(None))

    def test_session_expires(self):
        store = SessionStore(ttl_seconds=100)
        token = store.create(AuthUser(sub="s", email="a@b.com"), now=1000.0)
        self.assertIsNotNone(store.get(token, now=1050.0))
        self.assertIsNone(store.get(token, now=1101.0))  # past TTL -> pruned

    def test_tokens_unique(self):
        store = SessionStore()
        u = AuthUser(sub="s", email="a@b.com")
        self.assertNotEqual(store.create(u), store.create(u))


class StateStoreTests(unittest.TestCase):
    def test_issue_then_consume_once(self):
        store = StateStore(ttl_seconds=600)
        state = store.issue(now=1000.0)
        self.assertTrue(store.consume(state, now=1001.0))
        self.assertFalse(store.consume(state, now=1002.0))  # single use

    def test_expired_state_rejected(self):
        store = StateStore(ttl_seconds=10)
        state = store.issue(now=1000.0)
        self.assertFalse(store.consume(state, now=1011.0))

    def test_unknown_state_rejected(self):
        self.assertFalse(StateStore().consume("nope", now=1.0))
        self.assertFalse(StateStore().consume(None, now=1.0))


class GoogleOAuthTests(unittest.TestCase):
    def test_not_configured(self):
        g = GoogleOAuth(client_id="", client_secret="", redirect_uri="")
        self.assertFalse(g.configured)
        with self.assertRaises(GoogleOAuthError):
            g.build_authorize_url("state123")
        with self.assertRaises(GoogleOAuthError):
            g.complete_login("code")

    def test_authorize_url(self):
        g = GoogleOAuth(client_id="cid", client_secret="sec", redirect_uri="https://app/cb")
        url = g.build_authorize_url("st8")
        self.assertTrue(url.startswith("https://accounts.google.com/o/oauth2/v2/auth?"))
        self.assertIn("client_id=cid", url)
        self.assertIn("state=st8", url)
        self.assertIn("response_type=code", url)

    def test_complete_login_with_mocked_http(self):
        g = GoogleOAuth(client_id="cid", client_secret="sec", redirect_uri="https://app/cb")
        with (
            mock.patch.object(google_mod, "_http_post_form", return_value={"access_token": "at"}),
            mock.patch.object(
                google_mod,
                "_http_get_json",
                return_value={"sub": "g-123", "email": "u@gmail.com", "name": "U"},
            ),
        ):
            user = g.complete_login("authcode")
        self.assertEqual(user.sub, "g-123")
        self.assertEqual(user.email, "u@gmail.com")
        self.assertEqual(user.provider, "google")

    def test_complete_login_missing_access_token(self):
        g = GoogleOAuth(client_id="cid", client_secret="sec", redirect_uri="https://app/cb")
        with mock.patch.object(google_mod, "_http_post_form", return_value={}):
            with self.assertRaises(GoogleOAuthError):
                g.complete_login("authcode")

    def test_complete_login_missing_identity(self):
        g = GoogleOAuth(client_id="cid", client_secret="sec", redirect_uri="https://app/cb")
        with (
            mock.patch.object(google_mod, "_http_post_form", return_value={"access_token": "at"}),
            mock.patch.object(google_mod, "_http_get_json", return_value={"sub": "x"}),  # no email
        ):
            with self.assertRaises(GoogleOAuthError):
                g.complete_login("authcode")

    def test_complete_login_wraps_http_errors(self):
        # A network/HTTP failure must surface as GoogleOAuthError (callback -> 400),
        # not bubble up as a raw exception (which would be a 500).
        g = GoogleOAuth(client_id="cid", client_secret="sec", redirect_uri="https://app/cb")
        with mock.patch.object(google_mod, "_http_post_form", side_effect=OSError("connection refused")):
            with self.assertRaises(GoogleOAuthError):
                g.complete_login("authcode")

    def test_complete_login_rejects_unverified_email(self):
        g = GoogleOAuth(client_id="cid", client_secret="sec", redirect_uri="https://app/cb")
        with (
            mock.patch.object(google_mod, "_http_post_form", return_value={"access_token": "at"}),
            mock.patch.object(
                google_mod,
                "_http_get_json",
                return_value={"sub": "g", "email": "u@x.com", "email_verified": False},
            ),
        ):
            with self.assertRaises(GoogleOAuthError):
                g.complete_login("authcode")


class _StubGoogle:
    def __init__(self, configured: bool):
        self.configured = configured

    def build_authorize_url(self, state: str) -> str:
        return f"https://accounts.google.com/o/oauth2/v2/auth?state={state}"

    def complete_login(self, code: str) -> AuthUser:
        return AuthUser(sub="g1", email="picked@gmail.com", name="Picked", provider="google")


class AuthRoutesTests(unittest.TestCase):
    def setUp(self):
        session_store.clear()
        self.client = TestClient(app)

    def test_me_unauthenticated(self):
        resp = self.client.get("/api/auth/me")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["authenticated"])

    def test_dev_login_then_me_then_logout(self):
        with mock.patch.dict("os.environ", {"TAXGLOBAL_ENABLE_DEV_LOGIN": "true"}, clear=False):
            resp = self.client.post("/api/auth/dev-login", json={"email": "shaw@example.com", "name": "Shaw"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["authenticated"])
        self.assertEqual(resp.json()["user"]["email"], "shaw@example.com")

        me = self.client.get("/api/auth/me")
        self.assertTrue(me.json()["authenticated"])
        self.assertEqual(me.json()["user"]["provider"], "dev")

        out = self.client.post("/api/auth/logout")
        self.assertFalse(out.json()["authenticated"])
        self.assertFalse(self.client.get("/api/auth/me").json()["authenticated"])

    def test_dev_login_disabled_by_default(self):
        # Unset/empty -> dev login must be OFF (safe default), returning 403.
        with mock.patch.dict("os.environ", {"TAXGLOBAL_ENABLE_DEV_LOGIN": ""}, clear=False):
            resp = self.client.post("/api/auth/dev-login", json={"email": "x@y.com"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "dev_login_disabled")

    def test_google_login_not_configured(self):
        with mock.patch.object(auth_routes, "google_oauth", _StubGoogle(configured=False)):
            resp = self.client.get("/api/auth/google/login")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"]["code"], "google_oauth_not_configured")

    def test_google_login_redirects_when_configured(self):
        with mock.patch.object(auth_routes, "google_oauth", _StubGoogle(configured=True)):
            resp = self.client.get("/api/auth/google/login", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("accounts.google.com", resp.headers["location"])

    def test_callback_invalid_state(self):
        resp = self.client.get("/api/auth/google/callback?code=c&state=bogus", follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "invalid_state")

    def test_callback_success_sets_session(self):
        from backend.auth.sessions import now_seconds

        valid_state = state_store.issue(now=now_seconds())
        with mock.patch.object(auth_routes, "google_oauth", _StubGoogle(configured=True)):
            resp = self.client.get(
                f"/api/auth/google/callback?code=authcode&state={valid_state}",
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 302)
        # session cookie now lets /me report the Google identity
        me = self.client.get("/api/auth/me")
        self.assertTrue(me.json()["authenticated"])
        self.assertEqual(me.json()["user"]["email"], "picked@gmail.com")


if __name__ == "__main__":
    unittest.main()
