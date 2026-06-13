"""Tests for M3.8 rate limiting on LLM-backed endpoints."""

from __future__ import annotations

import unittest

from starlette.testclient import TestClient

import backend.config as cfg
from backend.main import create_app
from backend.ratelimit import SlidingWindowLimiter, reset_limiters


class TestSlidingWindowLimiter(unittest.TestCase):
    def test_allows_up_to_limit_then_blocks(self) -> None:
        limiter = SlidingWindowLimiter(max_requests=3, window_seconds=60)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))

    def test_clients_are_independent(self) -> None:
        limiter = SlidingWindowLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))

    def test_window_expiry_frees_capacity(self) -> None:
        # window_seconds=0 → every prior hit is immediately stale.
        limiter = SlidingWindowLimiter(max_requests=1, window_seconds=0)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))


class TestRateLimitMiddleware(unittest.TestCase):
    def setUp(self) -> None:
        reset_limiters()
        self._saved = (cfg.ENABLE_RATE_LIMIT, cfg.RATE_LIMIT_ASSISTANT, cfg.RATE_LIMIT_DOCUMENTS)

    def tearDown(self) -> None:
        (cfg.ENABLE_RATE_LIMIT, cfg.RATE_LIMIT_ASSISTANT, cfg.RATE_LIMIT_DOCUMENTS) = self._saved
        reset_limiters()

    def test_disabled_by_default_no_throttle(self) -> None:
        cfg.ENABLE_RATE_LIMIT = False
        client = TestClient(create_app())
        for _ in range(30):
            r = client.post("/api/assistant/query", json={"query": "什么是 standard deduction"})
            self.assertEqual(r.status_code, 200)

    def test_assistant_throttled_when_enabled(self) -> None:
        cfg.ENABLE_RATE_LIMIT = True
        cfg.RATE_LIMIT_ASSISTANT = 3
        client = TestClient(create_app())
        codes = [
            client.post("/api/assistant/query", json={"query": "什么是 standard deduction"}).status_code
            for _ in range(5)
        ]
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3], 429)
        self.assertEqual(codes[4], 429)

    def test_429_envelope_and_retry_after(self) -> None:
        cfg.ENABLE_RATE_LIMIT = True
        cfg.RATE_LIMIT_ASSISTANT = 1
        client = TestClient(create_app())
        client.post("/api/assistant/query", json={"query": "hi"})
        blocked = client.post("/api/assistant/query", json={"query": "hi"})
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["error"]["code"], "rate_limited")
        self.assertIn("Retry-After", blocked.headers)

    def test_documents_have_own_limit(self) -> None:
        cfg.ENABLE_RATE_LIMIT = True
        cfg.RATE_LIMIT_ASSISTANT = 100
        cfg.RATE_LIMIT_DOCUMENTS = 2
        client = TestClient(create_app())
        codes = [
            client.post(
                "/api/documents/extract-w2", json={"image_base64": "x", "media_type": "image/png"}
            ).status_code
            for _ in range(4)
        ]
        # First 2 reach the handler (503 vision unavailable in tests), then throttled.
        self.assertNotIn(429, codes[:2])
        self.assertEqual(codes[2], 429)
        self.assertEqual(codes[3], 429)

    def test_non_llm_endpoints_never_throttled(self) -> None:
        cfg.ENABLE_RATE_LIMIT = True
        cfg.RATE_LIMIT_ASSISTANT = 1
        client = TestClient(create_app())
        for _ in range(10):
            self.assertEqual(client.get("/api/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
