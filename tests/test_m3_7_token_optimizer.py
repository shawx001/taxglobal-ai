"""Tests for M3.7 token optimization + usage tracking."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from backend.llm.provider import MockProvider
from backend.llm.token_optimizer import compress_knowledge_context, estimate_tokens
from backend.llm.usage_tracker import (
    TrackedProvider,
    record_usage,
    reset_usage,
    usage_summary,
)
from backend.main import create_app


class TestEstimateTokens(unittest.TestCase):
    def test_empty_is_zero(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)

    def test_ascii_roughly_quarter(self) -> None:
        tokens = estimate_tokens("a" * 400)
        self.assertGreaterEqual(tokens, 80)
        self.assertLessEqual(tokens, 200)

    def test_cjk_counts_heavier_than_ascii(self) -> None:
        self.assertGreater(estimate_tokens("税" * 100), estimate_tokens("a" * 100))


class TestCompressKnowledgeContext(unittest.TestCase):
    def test_caps_result_count(self) -> None:
        answer = {"type": "knowledge", "results": [{"text": f"chunk {i}"} for i in range(10)], "total": 10}
        compressed = compress_knowledge_context(answer)
        self.assertEqual(len(compressed["results"]), 3)

    def test_truncates_long_chunks(self) -> None:
        answer = {"type": "knowledge", "results": [{"text": "x" * 5000}], "total": 1}
        compressed = compress_knowledge_context(answer)
        self.assertLessEqual(len(compressed["results"][0]["text"]), 601)

    def test_preserves_sources(self) -> None:
        answer = {
            "type": "knowledge",
            "results": [{"text": "t", "sources": [{"source_id": "irs-pub-501"}]}],
            "total": 1,
        }
        compressed = compress_knowledge_context(answer)
        self.assertEqual(compressed["results"][0]["sources"], [{"source_id": "irs-pub-501"}])

    def test_original_answer_untouched(self) -> None:
        answer = {"type": "knowledge", "results": [{"text": "x" * 5000}], "total": 1}
        compress_knowledge_context(answer)
        self.assertEqual(len(answer["results"][0]["text"]), 5000)

    def test_skill_result_passthrough(self) -> None:
        answer = {"type": "skill_result", "data": {"total_tax": 24734.0}}
        self.assertIs(compress_knowledge_context(answer), answer)

    def test_truncation_never_ends_mid_amount(self) -> None:
        """A cut like '…$13,8' invites the LLM to complete a wrong figure."""
        text = "x" * 595 + " $13,875 and more text beyond the cap"
        compressed = compress_knowledge_context({"type": "knowledge", "results": [{"text": text}], "total": 1})
        out = compressed["results"][0]["text"]
        self.assertFalse(out.rstrip("…").rstrip()[-1:].isdigit(), out[-30:])
        self.assertNotIn("$13,8", out)


class TestUsageTracker(unittest.TestCase):
    def setUp(self) -> None:
        reset_usage()

    def tearDown(self) -> None:
        reset_usage()

    def test_record_and_summary(self) -> None:
        record_usage("deepseek-chat", {"prompt_tokens": 1_000_000, "completion_tokens": 500_000})
        record_usage("deepseek-chat", {"prompt_tokens": 1_000_000, "completion_tokens": 500_000})
        summary = usage_summary()
        self.assertEqual(summary["total_calls"], 2)
        day = next(iter(summary["days"].values()))
        bucket = day["deepseek-chat"]
        self.assertEqual(bucket["prompt_tokens"], 2_000_000)
        self.assertEqual(bucket["completion_tokens"], 1_000_000)
        # 2 MTok in × $0.14 + 1 MTok out × $0.28 = $0.56
        self.assertAlmostEqual(summary["estimated_total_cost_usd"], 0.56, places=4)

    def test_malformed_usage_never_raises(self) -> None:
        record_usage("m", {"prompt_tokens": "abc"})  # type: ignore[dict-item]
        self.assertEqual(usage_summary()["total_calls"], 0)

    def test_tracked_provider_counts_calls(self) -> None:
        provider = TrackedProvider(MockProvider())
        provider.complete([])
        provider.complete([])
        self.assertEqual(usage_summary()["total_calls"], 2)

    def test_stream_counted_at_call_time(self) -> None:
        provider = TrackedProvider(MockProvider())
        provider.stream([])  # never consumed — still counted
        self.assertEqual(usage_summary()["total_calls"], 1)

    def test_negative_tokens_clamped(self) -> None:
        record_usage("m", {"prompt_tokens": -50, "completion_tokens": -10})
        summary = usage_summary()
        self.assertGreaterEqual(summary["estimated_total_cost_usd"], 0)

    def test_malformed_price_env_never_crashes(self) -> None:
        from decimal import Decimal

        from backend.llm.usage_tracker import _parse_price

        self.assertEqual(_parse_price("abc", "0.14"), Decimal("0.14"))
        self.assertEqual(_parse_price("", "0.14"), Decimal("0.14"))
        self.assertEqual(_parse_price("-1", "0.14"), Decimal("0.14"))
        self.assertEqual(_parse_price("0.5", "0.14"), Decimal("0.5"))

    def test_per_model_buckets_kept_separate(self) -> None:
        """Vision and chat models aggregate into distinct buckets."""
        record_usage("deepseek-chat", {"prompt_tokens": 10, "completion_tokens": 5})
        record_usage("vision-model", {"prompt_tokens": 900, "completion_tokens": 100})
        day = next(iter(usage_summary()["days"].values()))
        self.assertIn("deepseek-chat", day)
        self.assertIn("vision-model", day)


class TestLlmUsageEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    def setUp(self) -> None:
        reset_usage()

    def tearDown(self) -> None:
        reset_usage()

    def test_rejected_without_token(self) -> None:
        with patch.dict(os.environ, {"TAXGLOBAL_ADMIN_AUDIT_TOKEN": "secret-token"}):
            response = self.client.get("/api/admin/llm-usage")
        self.assertEqual(response.status_code, 403)

    def test_rejected_with_wrong_token(self) -> None:
        with patch.dict(os.environ, {"TAXGLOBAL_ADMIN_AUDIT_TOKEN": "secret-token"}):
            response = self.client.get("/api/admin/llm-usage", headers={"X-Admin-Token": "wrong"})
        self.assertEqual(response.status_code, 403)

    def test_summary_with_valid_token(self) -> None:
        record_usage("deepseek-chat", {"prompt_tokens": 10, "completion_tokens": 5})
        with patch.dict(os.environ, {"TAXGLOBAL_ADMIN_AUDIT_TOKEN": "secret-token"}):
            response = self.client.get("/api/admin/llm-usage", headers={"X-Admin-Token": "secret-token"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_calls"], 1)
        self.assertEqual(body["persistence"], "in_memory_per_worker_resets_on_restart")


if __name__ == "__main__":
    unittest.main()
