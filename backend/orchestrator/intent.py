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
