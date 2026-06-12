"""Tests for M3.3 LLM natural-language response generation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import backend.config as cfg
from backend.llm.provider import LLMResponse, MockProvider
from backend.orchestrator.nodes import format_node
from backend.orchestrator.response import llm_format_response


def _skill_state(query: str = "加州年薪15万交多少税") -> dict:
    return {
        "query": query,
        "intent": "income_tax",
        "confidence": "keyword_match",
        "matched_keyword": "所得税",
        "skill_output": {
            "result": {"total_tax": "24734.00", "effective_rate": "0.1649"},
            "source_attribution": "IRS Rev. Proc. 2024-40",
            "engine_function": "calculate_income_tax",
        },
        "nodes_visited": [],
    }


def _knowledge_state(query: str = "什么是 standard deduction") -> dict:
    return {
        "query": query,
        "intent": "knowledge",
        "confidence": "keyword_match",
        "matched_keyword": "什么是",
        "kb_results": {
            "results": [{"text": "Standard deduction is...", "sources": [{"source_id": "irs-pub-501"}]}],
            "total": 1,
        },
        "nodes_visited": [],
    }


class TestLLMFormatResponse(unittest.TestCase):
    """Unit tests for llm_format_response()."""

    @patch("backend.llm.client.get_provider")
    def test_returns_text_on_success(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue("你的联邦税是 $24,734.00，来源：IRS Rev. Proc. 2024-40。")
        mock_get_provider.return_value = provider
        text = llm_format_response(
            "加州年薪15万交多少税",
            {"type": "skill_result", "data": {"total_tax": "24734.00"}},
            ["IRS Rev. Proc. 2024-40"],
        )
        self.assertIsNotNone(text)
        self.assertIn("$24,734.00", text)

    @patch("backend.llm.client.get_provider")
    def test_returns_none_when_provider_unavailable(self, mock_get_provider):
        mock_get_provider.return_value = None
        text = llm_format_response("query", {"type": "skill_result"}, [])
        self.assertIsNone(text)

    @patch("backend.llm.client.get_provider")
    def test_returns_none_when_complete_raises(self, mock_get_provider):
        class RaisingProvider(MockProvider):
            def complete(self, messages, **kwargs):
                raise RuntimeError("network timeout")

        mock_get_provider.return_value = RaisingProvider()
        text = llm_format_response("query", {"type": "skill_result"}, [])
        self.assertIsNone(text)

    @patch("backend.llm.client.get_provider")
    def test_returns_none_when_complete_returns_none(self, mock_get_provider):
        class FailingProvider(MockProvider):
            def complete(self, messages, **kwargs):
                return None

        mock_get_provider.return_value = FailingProvider()
        text = llm_format_response("query", {"type": "skill_result"}, [])
        self.assertIsNone(text)

    @patch("backend.llm.client.get_provider")
    def test_returns_none_on_empty_text(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue("   \n  ")
        mock_get_provider.return_value = provider
        text = llm_format_response("query", {"type": "skill_result"}, [])
        self.assertIsNone(text)

    @patch("backend.llm.client.get_provider")
    def test_returns_none_on_non_string_content(self, mock_get_provider):
        class WeirdProvider(MockProvider):
            def complete(self, messages, **kwargs):
                return LLMResponse(content=None, model="mock")

        mock_get_provider.return_value = WeirdProvider()
        text = llm_format_response("query", {"type": "skill_result"}, [])
        self.assertIsNone(text)

    @patch("backend.llm.client.get_provider")
    def test_returns_none_on_unserializable_answer(self, mock_get_provider):
        mock_get_provider.return_value = MockProvider()
        circular: dict = {}
        circular["self"] = circular
        text = llm_format_response("query", circular, [])
        self.assertIsNone(text)

    @patch("backend.llm.client.get_provider")
    def test_engine_amounts_included_in_prompt(self, mock_get_provider):
        """The exact engine amount must reach the LLM prompt verbatim."""
        captured = {}

        class CapturingProvider(MockProvider):
            def complete(self, messages, **kwargs):
                captured["user"] = messages[-1].content
                return super().complete(messages, **kwargs)

        mock_get_provider.return_value = CapturingProvider()
        llm_format_response("query", {"data": {"total_tax": "24734.00"}}, ["IRS Rev. Proc. 2024-40"])
        self.assertIn("24734.00", captured["user"])
        self.assertIn("IRS Rev. Proc. 2024-40", captured["user"])


class TestFormatNodeLLMText(unittest.TestCase):
    """Integration tests for format_node + answer_text."""

    def test_no_answer_text_when_llm_disabled(self):
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = False
            result = format_node(_skill_state())
            self.assertNotIn("answer_text", result["response"])
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_answer_text_added_on_skill_result(self, mock_get_provider):
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue("你的联邦税是 $24,734.00。来源：IRS Rev. Proc. 2024-40。")
            mock_get_provider.return_value = provider
            result = format_node(_skill_state())
            self.assertIn("answer_text", result["response"])
            self.assertIn("$24,734.00", result["response"]["answer_text"])
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_structured_answer_untouched_by_llm(self, mock_get_provider):
        """LLM text is additive — engine numbers stay verbatim in answer."""
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue("乱改的数字 $99,999.00")
            provider.enqueue("重写后还是乱改 $99,999.00")  # retry also tampered
            mock_get_provider.return_value = provider
            with self.assertLogs("taxglobal.orchestrator", level="WARNING"):
                result = format_node(_skill_state())
            self.assertEqual(result["response"]["answer"]["data"]["total_tax"], "24734.00")
            self.assertEqual(result["response"]["sources"], ["IRS Rev. Proc. 2024-40"])
            self.assertNotIn("answer_text", result["response"])
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_answer_text_added_on_knowledge(self, mock_get_provider):
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue("Standard deduction 是标准扣除额，来源 irs-pub-501。")
            mock_get_provider.return_value = provider
            result = format_node(_knowledge_state())
            self.assertIn("answer_text", result["response"])
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_fallback_keeps_template_when_llm_fails(self, mock_get_provider):
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            mock_get_provider.return_value = None
            result = format_node(_skill_state())
            self.assertNotIn("answer_text", result["response"])
            self.assertEqual(result["response"]["answer"]["data"]["total_tax"], "24734.00")
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_missing_params_gets_conversational_text(self, mock_get_provider):
        """Missing inputs → LLM explains conversationally instead of a bare template.

        (Design changed 2026-06-11 per Shaw: hardcoded parameter prompts are
        too stiff — the LLM answers the underlying question and asks for the
        inputs in human terms.)
        """
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue("美国公民海外收入也要申报。你去年在海外住了多少天、收入多少？我可以帮你精确算。")
            mock_get_provider.return_value = provider
            state = _skill_state(query="我在日本生活怎么报税")
            state["intent"] = "feie"
            state["error"] = "missing_skill_params"
            state["missing_params"] = ["foreign_earned_income", "days_abroad"]
            result = format_node(state)
            self.assertIn("answer_text", result["response"])
            self.assertEqual(result["response"]["answer"]["type"], "clarification")
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_llm_not_called_on_guardrail_blocked(self, mock_get_provider):
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            state = _skill_state()
            state["error"] = "guardrail_blocked"
            result = format_node(state)
            self.assertNotIn("answer_text", result["response"])
            mock_get_provider.assert_not_called()
        finally:
            cfg.ENABLE_LLM = original

    def test_m2_response_schema_unchanged_when_disabled(self):
        """ENABLE_LLM=false → response keys identical to M2."""
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = False
            result = format_node(_skill_state())
            self.assertEqual(
                set(result["response"].keys()),
                {"intent", "confidence", "answer", "sources", "tips", "trace"},
            )
        finally:
            cfg.ENABLE_LLM = original


if __name__ == "__main__":
    unittest.main()
