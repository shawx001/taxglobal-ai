"""Deterministic keyword-based intent classifier for M2."""

from __future__ import annotations

from dataclasses import dataclass

INTENT_INCOME_TAX = "income_tax"
INTENT_FEIE = "feie"
INTENT_RSU = "rsu"
INTENT_CRYPTO = "crypto"
INTENT_NEXUS = "nexus"
INTENT_KNOWLEDGE = "knowledge"
INTENT_CLARIFY = "clarify"

INTENT_KEYWORDS: dict[str, list[str]] = {
    INTENT_FEIE: [
        "feie",
        "海外收入",
        "foreign earned",
        "330天",
        "330 day",
        "海外工作",
        "expatriate",
        "form 2555",
        "bona fide",
        "physical presence",
        "海外豁免",
    ],
    INTENT_RSU: [
        "rsu",
        "restricted stock",
        "股票归属",
        "受限股票",
        "vesting",
        "归属",
        "equity compensation",
    ],
    INTENT_CRYPTO: [
        "crypto",
        "加密",
        "比特币",
        "bitcoin",
        "ethereum",
        "以太坊",
        "capital gain",
        "资本利得",
        "coin",
        "token",
        "nft",
        "wash sale",
        "cost basis",
        "成本基",
    ],
    INTENT_NEXUS: [
        "nexus",
        "经济联结",
        "sales tax",
        "电商",
        "远程销售",
        "wayfair",
        "economic nexus",
        "销售税",
    ],
    INTENT_INCOME_TAX: [
        "所得税",
        "income tax",
        "federal tax",
        "报税",
        "收入税",
        "州税",
        "state tax",
        "交多少税",
        "税率",
        "tax rate",
        "filing status",
        "自雇税",
        "self-employment",
        "fica",
        "收入",
    ],
    INTENT_KNOWLEDGE: [
        "怎么",
        "什么是",
        "how",
        "what is",
        "when",
        "deadline",
        "截止",
        "扣除",
        "deduction",
        "抵免",
        "credit",
        "explain",
        "解释",
        "规定",
        "regulation",
        "rule",
        "是什么意思",
        "什么意思",
        "是什么",
    ],
}

INTENT_SKILL_MAP: dict[str, str] = {
    INTENT_INCOME_TAX: "calculate_income_tax",
    INTENT_FEIE: "assess_feie",
    INTENT_RSU: "analyze_rsu",
    INTENT_CRYPTO: "track_crypto",
    INTENT_NEXUS: "detect_nexus",
}

_KNOWLEDGE_PREFIXES = (
    "what is", "how does", "how do", "explain",
    "怎么", "什么是", "解释", "是什么意思", "什么意思", "是什么",
)


@dataclass(frozen=True)
class ClassifyResult:
    """Intent classification output."""

    intent: str
    confidence: str
    matched_keyword: str


def classify_intent(query: str) -> ClassifyResult:
    """Classify a user query into a deterministic M2 intent."""

    query_lower = query.lower()
    if any(prefix in query_lower for prefix in _KNOWLEDGE_PREFIXES):
        for keyword in INTENT_KEYWORDS[INTENT_KNOWLEDGE]:
            if keyword.lower() in query_lower:
                return ClassifyResult(intent=INTENT_KNOWLEDGE, confidence="keyword_match", matched_keyword=keyword)
    for intent, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in query_lower:
                return ClassifyResult(intent=intent, confidence="keyword_match", matched_keyword=keyword)
    return ClassifyResult(intent=INTENT_CLARIFY, confidence="fallback", matched_keyword="")


# ---------------------------------------------------------------------------
# M3.2: LLM-enhanced intent classification
# ---------------------------------------------------------------------------

import json  # noqa: E402
import logging  # noqa: E402
import math  # noqa: E402

logger = logging.getLogger("taxglobal.orchestrator")

_VALID_INTENTS = frozenset({
    INTENT_INCOME_TAX, INTENT_FEIE, INTENT_RSU, INTENT_CRYPTO,
    INTENT_NEXUS, INTENT_KNOWLEDGE, INTENT_CLARIFY,
})

_LLM_CONFIDENCE_THRESHOLD = 0.6

_INTENT_SYSTEM_PROMPT = """\
You are a tax query intent classifier for TaxGlobal AI.
Classify the user's query into exactly ONE of these intents:

- income_tax: Federal/state income tax calculation, tax rates, filing status, W-2, self-employment, FICA
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

    Returns ``ClassifyResult`` on success, ``None`` on any failure so the
    caller can fall back to keyword classification.
    """

    from backend.llm.client import get_provider
    from backend.llm.provider import LLMMessage

    provider = get_provider()
    if provider is None:
        return None

    messages = [
        LLMMessage(role="system", content=_INTENT_SYSTEM_PROMPT),
        LLMMessage(role="user", content=query),
    ]

    try:
        response = provider.complete(messages, temperature=0.0, max_tokens=64)
    except Exception:
        logger.exception("LLM provider.complete() failed, falling back to keyword")
        return None
    if response is None:
        return None

    content = response.content if isinstance(response.content, str) else ""
    try:
        parsed = json.loads(content.strip())
    except (json.JSONDecodeError, ValueError):
        # Do not log response content — it may echo user-provided PII.
        logger.warning(
            "LLM intent response not valid JSON (model=%s, len=%d)",
            response.model,
            len(content),
        )
        return None
    if not isinstance(parsed, dict):
        logger.warning("LLM intent response is not a JSON object (model=%s)", response.model)
        return None

    intent = str(parsed.get("intent", "")).strip().lower()
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
        confidence = 0.0

    if intent not in _VALID_INTENTS:
        logger.warning("LLM returned invalid intent: %s", intent[:40])
        return None

    if confidence < _LLM_CONFIDENCE_THRESHOLD:
        logger.info(
            "LLM confidence %.2f below threshold %.2f, falling back",
            confidence,
            _LLM_CONFIDENCE_THRESHOLD,
        )
        return None

    return ClassifyResult(
        intent=intent,
        confidence=f"llm:{confidence:.2f}",
        matched_keyword="",
    )
