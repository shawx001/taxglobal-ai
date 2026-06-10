"""M3.4 fact-checker guardrail for LLM-generated answer text.

Verifies that every dollar amount in the LLM's natural-language answer
matches an amount present in the structured engine answer, to the cent.
Pure local validation: no LLM calls, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

VERDICT_PASS = "pass"
VERDICT_WARN = "warn"
VERDICT_BLOCK = "block"

_CENT = Decimal("0.01")

_DOLLAR_AMOUNT_PATTERN = re.compile(
    r"(?P<paren>\()?\s*(?P<prefix>-)?\$\s*(?P<post>-)?\s*"
    r"(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?![\d,])\)?"
)
_NON_MONEY_KEYS = {
    "confidence",
    "count",
    "days",
    "days_abroad",
    "effective_rate",
    "filing_year",
    "finish_reason",
    "marginal_rate",
    "rate",
    "shares",
    "tax_year",
    "total",
    "transaction_count",
    "year",
}
_MONEY_KEY_MARKERS = (
    "agi",
    "amount",
    "basis",
    "base",
    "credit",
    "deduction",
    "exclusion",
    "fica",
    "gain",
    "income",
    "liability",
    "loss",
    "niit",
    "payroll",
    "proceeds",
    "qbi",
    "tax",
    "taxable",
    "value",
    "wage",
    "withheld",
)
_ADVICE_PATTERNS = (
    "投资",
    "理财",
    "买保险",
    "开公司",
    "炒股",
    "invest",
    "buy insurance",
    "financial advis",
)
_ABSOLUTE_PATTERNS = ("保证", "一定能", "肯定能", "guarantee", "definitely will")


@dataclass(frozen=True)
class FactCheckResult:
    """Fact-check verdict for an LLM answer_text."""

    verdict: str
    issues: list[str] = field(default_factory=list)


def _to_cent_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "")).quantize(_CENT)
    except (InvalidOperation, ValueError):
        return None


def _extract_dollar_amounts(text: str) -> list[Decimal]:
    amounts: list[Decimal] = []
    for match in _DOLLAR_AMOUNT_PATTERN.finditer(text):
        amount = _to_cent_decimal(match.group("number"))
        if amount is not None:
            if match.group("paren") or match.group("prefix") or match.group("post"):
                amount = -amount
            amounts.append(amount)
    return amounts


def _is_money_key(key: str) -> bool:
    normalized = key.lower()
    if normalized in _NON_MONEY_KEYS:
        return False
    if normalized.endswith("_rate") or normalized.endswith("_count") or normalized.endswith("_year"):
        return False
    return any(marker in normalized for marker in _MONEY_KEY_MARKERS)


def _collect_engine_numbers(value: Any, out: set[Decimal], key: str = "") -> None:
    """Recursively collect money-like numeric leaves from engine output."""

    if isinstance(value, bool):
        return
    if isinstance(value, (int, float, str)):
        if _is_money_key(key):
            amount = _to_cent_decimal(value)
            if amount is not None:
                out.add(amount)
        return
    if isinstance(value, dict):
        for item_key, item in value.items():
            _collect_engine_numbers(item, out, str(item_key))
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_engine_numbers(item, out, key)


def check_response_fidelity(answer_text: str, answer: dict[str, Any], sources: list[str]) -> FactCheckResult:
    """Validate LLM answer text against structured engine output.

    Any unmatched dollar amount blocks the text. Non-fatal language issues
    are returned as WARN annotations without dropping the answer_text.
    """

    engine_numbers: set[Decimal] = set()
    _collect_engine_numbers(answer, engine_numbers)

    for amount in _extract_dollar_amounts(answer_text):
        if amount not in engine_numbers:
            return FactCheckResult(
                verdict=VERDICT_BLOCK,
                issues=["llm_amount_not_in_engine_output"],
            )

    issues: list[str] = []
    text_lower = answer_text.lower()
    if any(pattern in text_lower for pattern in _ADVICE_PATTERNS):
        issues.append("out_of_scope_advice")
    if any(pattern in text_lower for pattern in _ABSOLUTE_PATTERNS):
        issues.append("absolute_claim")
    if sources and not any(str(source) in answer_text for source in sources):
        issues.append("no_source_cited")

    if issues:
        return FactCheckResult(verdict=VERDICT_WARN, issues=issues)
    return FactCheckResult(verdict=VERDICT_PASS)
