"""Tests for M3.2 LLM-enhanced intent classification."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import backend.config as cfg
from backend.llm.provider import MockProvider
from backend.orchestrator.intent import classify_intent, llm_classify_intent


class TestLLMClassifyIntent(unittest.TestCase):
    """Test the LLM-enhanced classifier."""

    @patch("backend.llm.client.get_provider")
    def test_returns_llm_result_on_success(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "income_tax", "confidence": 0.95}))
        mock_get_provider.return_value = provider

        result = llm_classify_intent("我在加州年收入15万要交多少税")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent, "income_tax")
        self.assertEqual(result.confidence, "llm:0.95")
        self.assertEqual(result.matched_keyword, "")

    @patch("backend.llm.client.get_provider")
    def test_returns_none_when_provider_unavailable(self, mock_get_provider):
        mock_get_provider.return_value = None
        result = llm_classify_intent("some query")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_returns_none_on_invalid_json(self, mock_get_provider):
        provider = MockProvider(default_response="I think this is about income tax")
        mock_get_provider.return_value = provider
        result = llm_classify_intent("test query")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_returns_none_on_invalid_intent(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "mortgage", "confidence": 0.9}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("how do I refinance")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_returns_none_on_low_confidence(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "feie", "confidence": 0.3}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("something about travel")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_confidence_at_threshold_succeeds(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "feie", "confidence": 0.6}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("I worked overseas")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent, "feie")

    @patch("backend.llm.client.get_provider")
    def test_confidence_just_below_threshold_fails(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "feie", "confidence": 0.59}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("I worked overseas")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_feie_classification(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "feie", "confidence": 0.88}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("I worked in Singapore for 11 months, how do I exclude my income?")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent, "feie")

    @patch("backend.llm.client.get_provider")
    def test_knowledge_classification(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "knowledge", "confidence": 0.91}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("QBI deduction 具体怎么算的")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent, "knowledge")

    @patch("backend.llm.client.get_provider")
    def test_nexus_classification(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "nexus", "confidence": 0.85}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("我在多个州有销售，需要注册吗")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent, "nexus")

    @patch("backend.llm.client.get_provider")
    def test_clarify_intent_accepted(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "clarify", "confidence": 0.8}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("hello world")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent, "clarify")

    @patch("backend.llm.client.get_provider")
    def test_handles_malformed_confidence(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "income_tax", "confidence": "high"}))
        mock_get_provider.return_value = provider
        # "high" can't convert to float → confidence=0.0 < threshold → None
        result = llm_classify_intent("tax question")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_handles_missing_intent_key(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"confidence": 0.9}))
        mock_get_provider.return_value = provider
        # Missing intent → "" → not in _VALID_INTENTS → None
        result = llm_classify_intent("tax question")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_provider_complete_returns_none(self, mock_get_provider):
        """Simulate provider.complete() returning None (network error, etc.)."""

        class FailingProvider(MockProvider):
            def complete(self, messages, **kwargs):
                return None

        mock_get_provider.return_value = FailingProvider()
        result = llm_classify_intent("test")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_json_array_returns_none(self, mock_get_provider):
        """Valid JSON that is not an object must fall back, not crash."""
        provider = MockProvider()
        provider.enqueue("[]")
        mock_get_provider.return_value = provider
        result = llm_classify_intent("tax question")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_json_null_returns_none(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue("null")
        mock_get_provider.return_value = provider
        result = llm_classify_intent("tax question")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_json_string_returns_none(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue('"income_tax"')
        mock_get_provider.return_value = provider
        result = llm_classify_intent("tax question")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_non_string_content_returns_none(self, mock_get_provider):
        """A provider returning non-string content must not crash."""
        from backend.llm.provider import LLMResponse

        class WeirdProvider(MockProvider):
            def complete(self, messages, **kwargs):
                return LLMResponse(content=None, model="mock")

        mock_get_provider.return_value = WeirdProvider()
        result = llm_classify_intent("tax question")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_provider_complete_raises_falls_back(self, mock_get_provider):
        """If provider.complete() raises, return None instead of propagating."""

        class RaisingProvider(MockProvider):
            def complete(self, messages, **kwargs):
                raise RuntimeError("network timeout")

        mock_get_provider.return_value = RaisingProvider()
        result = llm_classify_intent("tax question")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_nan_confidence_treated_as_zero(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "income_tax", "confidence": "nan"}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("tax question")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_inf_confidence_treated_as_zero(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "income_tax", "confidence": "inf"}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("tax question")
        self.assertIsNone(result)

    @patch("backend.llm.client.get_provider")
    def test_confidence_above_one_treated_as_zero(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "income_tax", "confidence": 1.5}))
        mock_get_provider.return_value = provider
        result = llm_classify_intent("tax question")
        self.assertIsNone(result)


class TestClassifyNodeFallback(unittest.TestCase):
    """Test that classify_node falls back to keyword when LLM is unavailable."""

    def test_keyword_fallback_when_llm_disabled(self):
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = False
            from backend.orchestrator.nodes import classify_node

            state = {"query": "我的所得税是多少", "nodes_visited": []}
            result = classify_node(state)
            self.assertEqual(result["intent"], "income_tax")
            self.assertEqual(result["confidence"], "keyword_match")
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_keyword_fallback_when_llm_fails(self, mock_get_provider):
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            mock_get_provider.return_value = None
            from backend.orchestrator.nodes import classify_node

            state = {"query": "我的所得税是多少", "nodes_visited": []}
            result = classify_node(state)
            self.assertEqual(result["intent"], "income_tax")
            self.assertEqual(result["confidence"], "keyword_match")
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_llm_result_used_when_available(self, mock_get_provider):
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue(json.dumps({"intent": "nexus", "confidence": 0.85}))
            mock_get_provider.return_value = provider
            from backend.orchestrator.nodes import classify_node

            state = {"query": "我在多个州有销售，需要注册吗", "nodes_visited": []}
            result = classify_node(state)
            self.assertEqual(result["intent"], "nexus")
            self.assertIn("llm:", result["confidence"])
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_low_confidence_falls_back_to_keyword(self, mock_get_provider):
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue(json.dumps({"intent": "crypto", "confidence": 0.4}))
            mock_get_provider.return_value = provider
            from backend.orchestrator.nodes import classify_node

            # "收入" matches income_tax keyword
            state = {"query": "我的收入有问题", "nodes_visited": []}
            result = classify_node(state)
            self.assertEqual(result["intent"], "income_tax")
            self.assertEqual(result["confidence"], "keyword_match")
        finally:
            cfg.ENABLE_LLM = original


class TestKeywordClassifierUnchanged(unittest.TestCase):
    """Verify M2 keyword classifier is completely unmodified."""

    def test_income_tax_keyword(self):
        result = classify_intent("我要算所得税")
        self.assertEqual(result.intent, "income_tax")
        self.assertEqual(result.confidence, "keyword_match")

    def test_feie_keyword(self):
        result = classify_intent("feie 海外收入排除")
        self.assertEqual(result.intent, "feie")

    def test_rsu_keyword(self):
        result = classify_intent("RSU vesting schedule")
        self.assertEqual(result.intent, "rsu")

    def test_crypto_keyword(self):
        result = classify_intent("bitcoin capital gain")
        self.assertEqual(result.intent, "crypto")

    def test_nexus_keyword(self):
        result = classify_intent("economic nexus 经济联结")
        self.assertEqual(result.intent, "nexus")

    def test_knowledge_keyword(self):
        result = classify_intent("什么是 standard deduction")
        self.assertEqual(result.intent, "knowledge")

    def test_clarify_fallback(self):
        result = classify_intent("hello")
        self.assertEqual(result.intent, "clarify")
        self.assertEqual(result.confidence, "fallback")


if __name__ == "__main__":
    unittest.main()
