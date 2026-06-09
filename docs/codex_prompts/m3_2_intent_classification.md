# Codex Prompt: M3.2 — LLM Intent Classification

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `backend/orchestrator/intent.py` → `backend/orchestrator/nodes.py` → `backend/orchestrator/graph.py` → `backend/orchestrator/state.py` → `backend/llm/client.py` → `backend/llm/provider.py`

## Task

Upgrade the orchestrator's intent classification from keyword-only to LLM-enhanced. When `ENABLE_LLM=true`, send the user query to the LLM provider (M3.1) for intent classification. The LLM returns a structured JSON with intent + confidence. When `ENABLE_LLM=false` (default), the existing M2 keyword path is used unchanged — zero behavioral difference.

**Why:** M2 keyword matching fails on natural language like "我在加州remote给纽约公司上班，税怎么交" (hits multiple intents — income_tax, nexus, knowledge). An LLM can understand the true intent from context.

## Architecture Decision (IMPORTANT — READ THIS)

**Shaw has explicitly approved external LLM API calls with PII sanitization (2026-06-08).** M3.1 already merged the `SanitizedProvider` decorator that masks SSN/email before any outbound call. **Do NOT add any new "external API" guards, warnings, or checks beyond what M3.1 already provides.** The PII sanitization is handled transparently by the provider layer — callers just call `provider.complete()` and PII is scrubbed automatically.

**LLM = ears + mouth, NEVER brain.** The LLM classifies intent and later generates natural language responses. It NEVER computes tax amounts. All numbers come from the rule engine. This is enforced by architecture: `classify_node` only outputs an intent string, not numbers.

## Core Constraints

1. **`ENABLE_LLM=false` → zero changes**: Existing `classify_intent()` keyword path is NEVER modified. New LLM path is a separate function.
2. **Fallback chain**: LLM fails/times out → fall back to keyword classifier. The user never sees an error from a broken LLM.
3. **Structured output**: LLM returns JSON `{"intent": "...", "confidence": 0.0-1.0}`. Parse with `json.loads()`, not eval.
4. **Confidence threshold**: LLM confidence < 0.6 → fall back to keyword classifier.
5. **No new intents**: The 7 M2 intents are the only valid outputs: `income_tax`, `feie`, `rsu`, `crypto`, `nexus`, `knowledge`, `clarify`.
6. **System prompt is deterministic**: Hardcoded in code, NOT loaded from LLM. The LLM is told exactly which intents exist and what each means.

## File 1: `backend/orchestrator/intent.py` — ADD `llm_classify_intent()`

Keep the `classify_intent()` implementation unchanged. Append the new LLM code below it.

```python
import json
import logging

from backend.llm.client import get_provider
from backend.llm.provider import LLMMessage

logger = logging.getLogger("taxglobal.orchestrator")

# Valid intents — the LLM must pick from this set
_VALID_INTENTS = frozenset({
    INTENT_INCOME_TAX, INTENT_FEIE, INTENT_RSU, INTENT_CRYPTO,
    INTENT_NEXUS, INTENT_KNOWLEDGE, INTENT_CLARIFY,
})

_LLM_CONFIDENCE_THRESHOLD = 0.6

_INTENT_SYSTEM_PROMPT = """\
You are a tax query intent classifier for TaxGlobal AI.
Classify the user's query into exactly ONE of these intents:

- income_tax: Questions about federal/state income tax calculation, tax rates, filing status, W-2 wages, self-employment tax, FICA
- feie: Foreign Earned Income Exclusion, working abroad, 330-day rule, Form 2555, bona fide residence
- rsu: Restricted Stock Units, vesting, equity compensation
- crypto: Cryptocurrency tax, capital gains/losses, cost basis, NFT, wash sales
- nexus: Economic nexus, sales tax obligations, remote selling, Wayfair
- knowledge: General tax knowledge questions (what is X, how does Y work, deadlines, deductions, credits, rules)
- clarify: Cannot determine intent, or query is off-topic / too vague

Respond with ONLY a JSON object, no markdown, no explanation:
{"intent": "<intent>", "confidence": <0.0-1.0>}
"""


def llm_classify_intent(query: str) -> ClassifyResult | None:
    """Classify intent using the LLM provider.

    Returns ClassifyResult on success, None on any failure (caller should
    fall back to keyword classification).
    """
    provider = get_provider()
    if provider is None:
        return None

    messages = [
        LLMMessage(role="system", content=_INTENT_SYSTEM_PROMPT),
        LLMMessage(role="user", content=query),
    ]

    response = provider.complete(messages, temperature=0.0, max_tokens=64)
    if response is None:
        return None

    try:
        parsed = json.loads(response.content.strip())
    except (json.JSONDecodeError, ValueError):
        logger.warning("LLM intent response not valid JSON: %s", response.content[:200])
        return None

    intent = parsed.get("intent", "").strip().lower()
    confidence = float(parsed.get("confidence", 0.0))

    if intent not in _VALID_INTENTS:
        logger.warning("LLM returned invalid intent: %s", intent)
        return None

    if confidence < _LLM_CONFIDENCE_THRESHOLD:
        logger.info("LLM confidence %.2f below threshold %.2f, falling back", confidence, _LLM_CONFIDENCE_THRESHOLD)
        return None

    return ClassifyResult(
        intent=intent,
        confidence=f"llm:{confidence:.2f}",
        matched_keyword="",
    )
```

## File 2: `backend/orchestrator/nodes.py` — MODIFY `classify_node()`

Replace ONLY the `classify_node()` function body. Do NOT touch any other function.

```python
def classify_node(state: AssistantState) -> dict[str, Any]:
    """Classify user intent — LLM-enhanced when available, keyword fallback."""

    query = state["query"]

    # Try LLM classification first (returns None if ENABLE_LLM=false or LLM fails)
    from backend import config
    if config.ENABLE_LLM:
        from backend.orchestrator.intent import llm_classify_intent
        llm_result = llm_classify_intent(query)
        if llm_result is not None:
            return {
                "intent": llm_result.intent,
                "confidence": llm_result.confidence,
                "matched_keyword": llm_result.matched_keyword,
                "nodes_visited": _visited(state, "classify"),
            }

    # Fallback: M2 keyword classification (always available)
    result = classify_intent(query)
    return {
        "intent": result.intent,
        "confidence": result.confidence,
        "matched_keyword": result.matched_keyword,
        "nodes_visited": _visited(state, "classify"),
    }
```

**Design notes:**
- The `config.ENABLE_LLM` check is done BEFORE importing `llm_classify_intent` to avoid unnecessary import when LLM is disabled.
- If `llm_classify_intent()` returns `None` (for ANY reason — provider down, bad JSON, low confidence, invalid intent), we silently fall back to keyword matching. The user never knows the LLM failed.
- The confidence format `"llm:0.92"` vs `"keyword_match"` lets downstream consumers (logging, analytics) distinguish LLM vs keyword classification.

## File 3: `backend/orchestrator/state.py` — NO CHANGES

The existing `AssistantState` already has `intent`, `confidence`, `matched_keyword` fields. No new fields needed for M3.2.

## File 4: `backend/orchestrator/graph.py` — NO CHANGES

The graph topology is unchanged. `classify_node` still feeds into the same conditional edges. The upgrade is transparent.

## Tests: `tests/test_m3_2_intent.py`

```python
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

    def _mock_response(self, intent: str, confidence: float) -> LLMResponse:
        return LLMResponse(
            content=json.dumps({"intent": intent, "confidence": confidence}),
            model="mock",
        )

    @patch("backend.llm.client.get_provider")
    def test_returns_llm_result_on_success(self, mock_get_provider):
        provider = MockProvider()
        provider.enqueue(json.dumps({"intent": "income_tax", "confidence": 0.95}))
        mock_get_provider.return_value = provider

        result = llm_classify_intent("我在加州年收入15万要交多少税")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent, "income_tax")
        self.assertEqual(result.confidence, "llm:0.95")

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
            mock_get_provider.return_value = None  # LLM unavailable
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


class TestKeywordClassifierUnchanged(unittest.TestCase):
    """Verify M2 keyword classifier is completely unmodified."""

    def test_income_tax_keyword(self):
        result = classify_intent("我要算所得税")
        self.assertEqual(result.intent, "income_tax")
        self.assertEqual(result.confidence, "keyword_match")

    def test_feie_keyword(self):
        result = classify_intent("feie 海外收入排除")
        self.assertEqual(result.intent, "feie")

    def test_knowledge_keyword(self):
        result = classify_intent("什么是 standard deduction")
        self.assertEqual(result.intent, "knowledge")

    def test_clarify_fallback(self):
        result = classify_intent("hello")
        self.assertEqual(result.intent, "clarify")
        self.assertEqual(result.confidence, "fallback")
```

## Acceptance Gates

```powershell
# 1. ALL existing tests still pass (keyword path untouched)
python -m unittest discover -s tests

# 2. New M3.2 tests pass
python -m unittest tests.test_m3_2_intent -v

# 3. Lint
python -m ruff check engine backend tests scripts

# 4. Verify keyword classifier function signature unchanged
python -c "from backend.orchestrator.intent import classify_intent; r = classify_intent('所得税'); assert r.intent == 'income_tax'; print('Keyword classifier OK')"

# 5. Verify LLM classifier exists
python -c "from backend.orchestrator.intent import llm_classify_intent; print('LLM classifier importable OK')"

# 6. Verify ENABLE_LLM=false still works end-to-end
python -c "
from backend.orchestrator.graph import run_assistant_query
r = run_assistant_query('我的所得税是多少', tax_year=2025)
assert r['intent'] == 'income_tax', f'got {r[\"intent\"]}'
print('E2E keyword path OK')
"
```

## Commit Format

```
feat(orchestrator): add M3.2 LLM-enhanced intent classification

Upgrade classify_node to try LLM classification first when ENABLE_LLM=true,
with automatic fallback to M2 keyword matching on any LLM failure (provider
down, invalid JSON, low confidence, invalid intent). Zero behavioral change
when ENABLE_LLM=false (default).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

## Notes for Codex

- **DO NOT modify** `classify_intent()` — it is the M2 keyword classifier and must remain byte-for-byte identical.
- **DO NOT add** any PII sanitization logic — M3.1's `SanitizedProvider` handles this transparently. Callers just call `provider.complete()`.
- **DO NOT add** any "external API" warnings, guards, or environment checks beyond `config.ENABLE_LLM`. Shaw has approved external LLM calls with PII sanitization (2026-06-08).
- **DO NOT add** new intents. The 7 M2 intents are the complete set for now.
- **DO NOT change** `graph.py` — the graph topology is unchanged. M3.2 only changes what happens INSIDE `classify_node`.
- **DO NOT change** `state.py` — existing fields are sufficient.
- The system prompt in `_INTENT_SYSTEM_PROMPT` is a constant string, NOT loaded from any file or database.
- `max_tokens=64` is intentional — the response is just `{"intent": "...", "confidence": 0.XX}`, never more than ~40 tokens.
- `temperature=0.0` is intentional — intent classification must be deterministic.
- Keep total new/changed code under 150 lines (excluding tests).
