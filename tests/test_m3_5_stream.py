"""Tests for the M3.5 assistant SSE stream endpoint."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import backend.config as cfg
from backend.llm.provider import MockProvider
from backend.main import create_app


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse SSE body text into [(event_name, data_dict), ...]."""

    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        name = ""
        data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
        if name:
            events.append((name, json.loads(data) if data else {}))
    return events


class TestStreamEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    def test_content_type_is_event_stream(self) -> None:
        response = self.client.post("/api/assistant/stream", json={"query": "什么是 standard deduction"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))

    def test_stream_carries_meta_answer_done(self) -> None:
        response = self.client.post("/api/assistant/stream", json={"query": "什么是 standard deduction"})
        events = _parse_sse(response.text)
        names = [name for name, _ in events]
        self.assertIn("meta", names)
        self.assertIn("answer", names)
        self.assertEqual(names[-1], "done")
        meta = dict(events)["meta"]
        self.assertEqual(meta["intent"], "knowledge")
        self.assertIn("sources", meta)

    def test_skill_intent_streams_engine_answer(self) -> None:
        response = self.client.post(
            "/api/assistant/stream", json={"query": "加州收入100000的所得税", "tax_year": 2025}
        )
        events = dict(_parse_sse(response.text))
        self.assertEqual(events["meta"]["intent"], "income_tax")
        self.assertEqual(events["answer"]["type"], "skill_result")

    def test_no_text_events_when_llm_disabled(self) -> None:
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = False
            response = self.client.post("/api/assistant/stream", json={"query": "什么是 standard deduction"})
            names = [name for name, _ in _parse_sse(response.text)]
            self.assertNotIn("text", names)
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_text_events_stream_verified_answer_text(self, mock_get_provider) -> None:
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            # 1st call: intent classification; 2nd call: response generation.
            provider.enqueue(json.dumps({"intent": "income_tax", "confidence": 0.95}))
            provider.enqueue("好的，规则引擎已经为你算好了，结果见下方明细。来源：IRS。")
            mock_get_provider.return_value = provider

            response = self.client.post(
                "/api/assistant/stream", json={"query": "加州收入100000的所得税", "tax_year": 2025}
            )
            events = _parse_sse(response.text)
            text = "".join(data["delta"] for name, data in events if name == "text")
            self.assertEqual(text, "好的，规则引擎已经为你算好了，结果见下方明细。来源：IRS。")
            meta = dict(events)["meta"]
            self.assertIn("fact_check", meta)
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_tampered_text_is_not_streamed(self, mock_get_provider) -> None:
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue(json.dumps({"intent": "income_tax", "confidence": 0.95}))
            provider.enqueue("你的税是 $99,999.00。")  # tampered → fact-checker blocks
            mock_get_provider.return_value = provider

            response = self.client.post(
                "/api/assistant/stream", json={"query": "加州收入100000的所得税", "tax_year": 2025}
            )
            events = _parse_sse(response.text)
            names = [name for name, _ in events]
            self.assertNotIn("text", names)
            self.assertEqual(dict(events)["answer"]["type"], "skill_result")
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_long_text_reassembles_across_chunks(self, mock_get_provider) -> None:
        """Multi-chunk CJK text: joined deltas must equal the original."""
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            long_text = "规则引擎已经完成了这次计算，结果在下方的明细里列出。" * 6 + "来源：IRS。"
            self.assertGreater(len(long_text), 96)
            provider = MockProvider()
            provider.enqueue(json.dumps({"intent": "income_tax", "confidence": 0.95}))
            provider.enqueue(long_text)
            mock_get_provider.return_value = provider

            response = self.client.post(
                "/api/assistant/stream", json={"query": "加州收入100000的所得税", "tax_year": 2025}
            )
            events = _parse_sse(response.text)
            deltas = [data["delta"] for name, data in events if name == "text"]
            self.assertGreater(len(deltas), 1)
            self.assertEqual("".join(deltas), long_text)
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_sse_framing_survives_embedded_sse_tokens(self, mock_get_provider) -> None:
        """answer_text containing SSE control sequences must not smuggle events."""
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            tricky = "第一行\n\nevent: fake\ndata: {}\n\n第二行。来源：IRS。"
            provider = MockProvider()
            provider.enqueue(json.dumps({"intent": "income_tax", "confidence": 0.95}))
            provider.enqueue(tricky)
            mock_get_provider.return_value = provider

            response = self.client.post(
                "/api/assistant/stream", json={"query": "加州收入100000的所得税", "tax_year": 2025}
            )
            events = _parse_sse(response.text)
            names = {name for name, _ in events}
            self.assertEqual(names, {"meta", "answer", "text", "done"})
            text = "".join(data["delta"] for name, data in events if name == "text")
            self.assertEqual(text, tricky)
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_warn_verdict_reaches_meta(self, mock_get_provider) -> None:
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue(json.dumps({"intent": "income_tax", "confidence": 0.95}))
            provider.enqueue("算好了，另外建议你投资指数基金。")  # advice → warn
            mock_get_provider.return_value = provider

            response = self.client.post(
                "/api/assistant/stream", json={"query": "加州收入100000的所得税", "tax_year": 2025}
            )
            events = dict(_parse_sse(response.text))
            self.assertEqual(events["meta"]["fact_check"]["verdict"], "warn")
            self.assertIn("out_of_scope_advice", events["meta"]["fact_check"]["issues"])
        finally:
            cfg.ENABLE_LLM = original

    def test_tax_year_inferred_from_query(self) -> None:
        """Query mentioning 2025 must compute with 2025 rules, not default 2026."""
        response = self.client.post("/api/assistant/stream", json={"query": "2025年加州收入100000的所得税"})
        events = dict(_parse_sse(response.text))
        self.assertEqual(events["answer"]["data"]["input"]["tax_year"], 2025)

    def test_explicit_tax_year_wins_over_query_text(self) -> None:
        response = self.client.post(
            "/api/assistant/stream",
            json={"query": "2025年加州收入100000的所得税", "tax_year": 2026},
        )
        events = dict(_parse_sse(response.text))
        self.assertEqual(events["answer"]["data"]["input"]["tax_year"], 2026)

    def test_empty_query_is_rejected(self) -> None:
        response = self.client.post("/api/assistant/stream", json={"query": ""})
        self.assertEqual(response.status_code, 422)

    def test_query_endpoint_still_plain_json(self) -> None:
        response = self.client.post("/api/assistant/query", json={"query": "什么是 standard deduction"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        self.assertEqual(response.json()["intent"], "knowledge")


if __name__ == "__main__":
    unittest.main()
