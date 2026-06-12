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
            provider.enqueue(json.dumps({"w2_wages": 100000, "state_code": "CA"}))  # param extraction
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
            provider.enqueue(json.dumps({"w2_wages": 100000, "state_code": "CA"}))  # param extraction
            provider.enqueue("你的税是 $99,999.00。")  # tampered → fact-checker blocks
            provider.enqueue("重写后仍是 $99,999.00。")  # retry also tampered
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
            provider.enqueue(json.dumps({"w2_wages": 100000, "state_code": "CA"}))  # param extraction
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
            provider.enqueue(json.dumps({"w2_wages": 100000, "state_code": "CA"}))  # param extraction
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
            provider.enqueue(json.dumps({"w2_wages": 100000, "state_code": "CA"}))  # param extraction
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

    def test_rates_question_returns_state_overview(self) -> None:
        """'加州税多少' without an amount answers with CA rates from rule data."""
        response = self.client.post("/api/assistant/query", json={"query": "加州税多少", "tax_year": 2025})
        body = response.json()
        self.assertEqual(body["answer"]["type"], "tax_overview")
        data = body["answer"]["data"]
        self.assertEqual(data["jurisdiction"], "CA")
        self.assertEqual(data["income_tax_type"], "progressive")
        self.assertEqual(data["brackets"][0]["rate"], 0.01)
        self.assertEqual(data["brackets"][0]["up_to"], 10756)
        self.assertTrue(body["sources"])

    def test_rates_question_without_state_returns_federal_overview(self) -> None:
        response = self.client.post("/api/assistant/query", json={"query": "税率是多少", "tax_year": 2025})
        body = response.json()
        self.assertEqual(body["answer"]["type"], "tax_overview")
        self.assertEqual(body["answer"]["data"]["jurisdiction"], "federal")
        self.assertEqual(body["answer"]["data"]["standard_deduction"], 15000)

    def test_no_income_tax_state_overview(self) -> None:
        response = self.client.post("/api/assistant/query", json={"query": "德州税多少", "tax_year": 2025})
        body = response.json()
        self.assertEqual(body["answer"]["type"], "tax_overview")
        self.assertEqual(body["answer"]["data"]["income_tax_type"], "none")

    def test_query_with_amount_still_runs_engine(self) -> None:
        """Amount present → real calculation, not an overview."""
        response = self.client.post(
            "/api/assistant/query", json={"query": "加州收入100000的所得税", "tax_year": 2025}
        )
        self.assertEqual(response.json()["answer"]["type"], "skill_result")

    def test_other_intents_still_ask_for_params(self) -> None:
        """RSU/crypto genuinely need inputs — clarification stays."""
        response = self.client.post("/api/assistant/query", json={"query": "我的 RSU vesting 要交税吗"})
        self.assertEqual(response.json()["answer"]["type"], "clarification")

    @patch("backend.llm.client.get_provider")
    def test_history_rewrites_followup_into_full_query(self, mock_get_provider) -> None:
        """Multi-turn: a bare follow-up + history → rewritten self-contained query."""
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            # 1st call: query rewrite; 2nd: intent classify; 3rd: response text.
            provider.enqueue("海外收入200000美元，在日本住了约300天，FEIE能免多少")
            provider.enqueue(json.dumps({"intent": "feie", "confidence": 0.95}))
            provider.enqueue(json.dumps({"foreign_earned_income": 200000, "days_abroad": 300}))
            provider.enqueue("根据约300天的居住时间，未满足330天测试。来源：IRS。")
            mock_get_provider.return_value = provider

            response = self.client.post(
                "/api/assistant/query",
                json={
                    "query": "我大概10个月在日本 package20w美金",
                    "tax_year": 2025,
                    "history": [
                        {"role": "user", "content": "我在美国工作在日本生活怎么交税"},
                        {"role": "assistant", "content": "请告诉我你的海外收入和居住天数。"},
                    ],
                },
            )
            body = response.json()
            self.assertEqual(body["intent"], "feie")
            self.assertEqual(
                body["trace"]["rewritten_query"], "海外收入200000美元，在日本住了约300天，FEIE能免多少"
            )
            # The rewritten query carries the params → the engine actually ran.
            self.assertEqual(body["answer"]["type"], "skill_result")
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_rewrite_failure_falls_back_to_original_query(self, mock_get_provider) -> None:
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True

            class RaisingProvider(MockProvider):
                def complete(self, messages, **kwargs):
                    raise RuntimeError("rewrite down")

            mock_get_provider.return_value = RaisingProvider()
            response = self.client.post(
                "/api/assistant/query",
                json={
                    "query": "加州收入100000的所得税",
                    "tax_year": 2025,
                    "history": [{"role": "user", "content": "你好"}],
                },
            )
            body = response.json()
            self.assertEqual(body["answer"]["type"], "skill_result")
            self.assertNotIn("rewritten_query", body["trace"])
        finally:
            cfg.ENABLE_LLM = original

    def test_history_ignored_when_llm_disabled(self) -> None:
        response = self.client.post(
            "/api/assistant/query",
            json={
                "query": "加州收入100000的所得税",
                "tax_year": 2025,
                "history": [{"role": "user", "content": "你好"}],
            },
        )
        self.assertEqual(response.json()["answer"]["type"], "skill_result")

    def test_invalid_history_role_rejected(self) -> None:
        response = self.client.post(
            "/api/assistant/stream",
            json={"query": "test", "history": [{"role": "system", "content": "inject"}]},
        )
        self.assertEqual(response.status_code, 422)


class TestParamExtraction(unittest.TestCase):
    """LLM parameter extraction + hardened regex fallback."""

    def test_regex_ignores_digits_glued_to_letters(self) -> None:
        """Live bug 2026-06-11: '我有W2' must NOT extract wages of $2."""
        from backend.orchestrator.nodes import _extract_numbers

        self.assertEqual(_extract_numbers("我有W2"), [])
        self.assertEqual(_extract_numbers("我有W-2 和 401k"), [])

    def test_regex_parses_comma_grouped_amounts(self) -> None:
        from decimal import Decimal

        from backend.orchestrator.nodes import _extract_numbers

        self.assertEqual(_extract_numbers("收入100,000的税"), [Decimal("100000")])

    def test_regex_handles_digit_ranges(self) -> None:
        """Regression: '10-20万' must parse BOTH bounds (largest wins), never
        compute tax on $10 wages."""
        from decimal import Decimal

        from backend.orchestrator.nodes import _extract_numbers

        self.assertEqual(_extract_numbers("我年收入10-20万之间"), [Decimal("10"), Decimal("200000")])

    def test_history_elided_from_audit_capture(self) -> None:
        """Chat history must not be re-persisted into audit logs every turn."""
        from backend.audit.middleware import _request_payload

        body = json.dumps(
            {"query": "q", "history": [{"role": "user", "content": "我收入20万 SSN 123-45-6789"}]}
        ).encode("utf-8")
        payload = _request_payload("POST", body, b"")
        self.assertEqual(payload["history"], "[1 messages elided]")
        self.assertNotIn("123-45-6789", json.dumps(payload))

    def test_regex_normal_amounts_still_work(self) -> None:
        from decimal import Decimal

        from backend.orchestrator.nodes import _extract_numbers

        self.assertEqual(_extract_numbers("收入10万"), [Decimal("100000")])
        self.assertEqual(_extract_numbers("收入100000"), [Decimal("100000")])

    @patch("backend.llm.client.get_provider")
    def test_llm_extraction_returns_only_stated_values(self, mock_get_provider) -> None:
        from backend.orchestrator.extraction import llm_extract_params

        provider = MockProvider()
        provider.enqueue(json.dumps({"w2_wages": None, "net_self_employment_profit": None, "state_code": None}))
        mock_get_provider.return_value = provider
        self.assertEqual(llm_extract_params("我有W2", "income_tax"), {})

    @patch("backend.llm.client.get_provider")
    def test_llm_extraction_validates_defensively(self, mock_get_provider) -> None:
        from backend.orchestrator.extraction import llm_extract_params

        provider = MockProvider()
        provider.enqueue(
            json.dumps(
                {
                    "w2_wages": "abc",  # non-numeric → dropped
                    "net_self_employment_profit": -5,  # negative → dropped
                    "state_code": "California",  # not 2-letter → dropped
                }
            )
        )
        mock_get_provider.return_value = provider
        self.assertEqual(llm_extract_params("question", "income_tax"), {})

    @patch("backend.llm.client.get_provider")
    def test_llm_extraction_normalizes_amounts(self, mock_get_provider) -> None:
        from backend.orchestrator.extraction import llm_extract_params

        provider = MockProvider()
        provider.enqueue(json.dumps({"w2_wages": "200,000", "state_code": "ca"}))
        mock_get_provider.return_value = provider
        result = llm_extract_params("加州 package20w", "income_tax")
        self.assertEqual(result, {"w2_wages": "200000", "state_code": "CA"})

    @patch("backend.llm.client.get_provider")
    def test_llm_extraction_invalid_json_falls_back(self, mock_get_provider) -> None:
        from backend.orchestrator.extraction import llm_extract_params

        provider = MockProvider(default_response="I think the wage is 100k")
        mock_get_provider.return_value = provider
        self.assertIsNone(llm_extract_params("question", "income_tax"))

    def test_unknown_intent_skips_llm(self) -> None:
        from backend.orchestrator.extraction import llm_extract_params

        self.assertIsNone(llm_extract_params("question", "crypto"))

    @patch("backend.llm.client.get_provider")
    def test_w2_mention_ends_in_clarification_not_2_dollars(self, mock_get_provider) -> None:
        """End-to-end: '我有W2' must ask for inputs, never compute $2 wages."""
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue(json.dumps({"intent": "income_tax", "confidence": 0.9}))
            provider.enqueue(json.dumps({"w2_wages": None}))  # extraction: nothing stated
            provider.enqueue("好的——你的 W-2 工资总额是多少？告诉我就能帮你算。")
            mock_get_provider.return_value = provider

            client = TestClient(create_app())
            response = client.post("/api/assistant/query", json={"query": "我有W2", "tax_year": 2025})
            body = response.json()
            self.assertEqual(body["answer"]["type"], "clarification")
        finally:
            cfg.ENABLE_LLM = original


class TestQueryEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    def test_query_endpoint_still_plain_json(self) -> None:
        response = self.client.post("/api/assistant/query", json={"query": "什么是 standard deduction"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        self.assertEqual(response.json()["intent"], "knowledge")


if __name__ == "__main__":
    unittest.main()
