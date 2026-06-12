"""M3.4 fact-checker guardrail for LLM-generated answer text.

Verifies that every dollar amount in the LLM's natural-language answer
matches an amount present in the structured engine answer, to the cent.
Pure local validation: no LLM calls, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

VERDICT_PASS = "pass"
VERDICT_WARN = "warn"
VERDICT_BLOCK = "block"

_CENT = Decimal("0.01")

# Trailing lookahead is (?!\d) only — NOT (?![\d,]): a prose comma right
# after an integer amount ("$99,999, including...") must not abort the
# match, or tampered amounts would evade extraction entirely.
_DOLLAR_AMOUNT_PATTERN = re.compile(
    r"(?P<paren>\()?\s*(?P<prefix>-)?\s*\$\s*(?P<post>-)?\s*"
    r"(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?!\d)\)?"
)

# Chinese-format USD amounts: "12万美元" / "200,000美金" / "1.5萬 美刀".
# Without this, an LLM writing "约12万美元" from memory slips past the
# $-only pattern (found live 2026-06-11).
_CN_USD_AMOUNT_PATTERN = re.compile(
    r"(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<wan>[万萬])?\s*美[元金刀]"
)

# "USD 130,000" prefix form.
_USD_PREFIX_PATTERN = re.compile(r"USD\s*(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)", re.IGNORECASE)

# "130k" / "$130k" shorthand (×1000). Well-known retirement-plan numbers
# (401k/403b/457b/529) are NOT amounts.
_K_SUFFIX_PATTERN = re.compile(r"(?<![\d.])(?P<number>\d+(?:\.\d+)?)[kK](?![A-Za-z0-9])")
_PLAN_NUMBERS = {"401", "403", "457", "529"}

# Chinese-numeral amounts ("十三万美元") can't be reliably converted —
# fail closed: their presence alone is unverifiable.
_CN_NUMERAL_USD_PATTERN = re.compile(r"[一二两三四五六七八九十百千]+\s*[万萬]?\s*美[元金刀]")
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
    "transaction_count",
    "year",
}
_MONEY_KEY_MARKERS = (
    "agi",
    "amount",
    "basis",
    "base",
    "cost",
    "credit",
    "deduction",
    "exclusion",
    "fica",
    "fmv",
    "gain",
    "income",
    "insurance",
    "liability",
    "limit",
    "loss",
    "niit",
    "payroll",
    "proceeds",
    "qbi",
    "tax",
    "taxable",
    "threshold",
    "ubia",
    "up_to",
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
        # Engine-side normalization: ROUND_HALF_UP to match engine/money.py.
        return Decimal(str(value).replace(",", "")).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _to_exact_decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _extract_dollar_amounts(text: str) -> list[Decimal]:
    """Extract $-amounts EXACTLY as written — no rounding.

    Rounding the text side would hide sub-cent tampering: "$24,734.005"
    must not collapse onto the engine's 24734.00. Decimal equality and
    hashing are numeric ("24734" == "24734.00"), so exact values still
    match the cent-quantized engine set.
    """

    amounts: list[Decimal] = []
    for match in _DOLLAR_AMOUNT_PATTERN.finditer(text):
        amount = _to_exact_decimal(match.group("number"))
        if amount is not None:
            if match.group("paren") or match.group("prefix") or match.group("post"):
                amount = -amount
            amounts.append(amount)
    for match in _CN_USD_AMOUNT_PATTERN.finditer(text):
        amount = _to_exact_decimal(match.group("number"))
        if amount is not None:
            if match.group("wan"):
                amount *= Decimal("10000")
            amounts.append(amount)
    for match in _USD_PREFIX_PATTERN.finditer(text):
        amount = _to_exact_decimal(match.group("number"))
        if amount is not None:
            amounts.append(amount)
    for match in _K_SUFFIX_PATTERN.finditer(text):
        if match.group("number") in _PLAN_NUMBERS:
            continue
        amount = _to_exact_decimal(match.group("number"))
        if amount is not None:
            amounts.append(amount * Decimal("1000"))
    return amounts


def _is_money_key(key: str) -> bool:
    normalized = key.lower()
    if normalized in _NON_MONEY_KEYS:
        return False
    if normalized.endswith("_rate") or normalized.endswith("_count") or normalized.endswith("_year"):
        return False
    return any(marker in normalized for marker in _MONEY_KEY_MARKERS)


def _is_money_total(key: str, value: Any) -> bool:
    """Engine money totals (crypto/payroll ``total``) are cent-quantized
    floats or decimal strings; knowledge-search ``total`` is an int count."""

    if key.lower() != "total":
        return False
    if isinstance(value, float):
        return True
    return isinstance(value, str) and "." in value


def _collect_engine_numbers(value: Any, out: set[Decimal], key: str = "") -> None:
    """Recursively collect money-like numeric leaves from engine output.

    String leaves are additionally scanned for $-amounts regardless of key:
    any amount already present in the structured answer (e.g. quoted inside
    a knowledge-base chunk) is user-visible, so the LLM citing it is not
    tampering.
    """

    if isinstance(value, bool):
        return
    if isinstance(value, str):
        if _is_money_key(key) or _is_money_total(key, value):
            amount = _to_cent_decimal(value)
            if amount is not None:
                out.add(amount)
        if "$" in value:
            out.update(_extract_dollar_amounts(value))
        return
    if isinstance(value, (int, float)):
        if _is_money_key(key) or _is_money_total(key, value):
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

    if _CN_NUMERAL_USD_PATTERN.search(answer_text):
        # "十三万美元" — unverifiable spelled-out amount; fail closed.
        return FactCheckResult(verdict=VERDICT_BLOCK, issues=["unverifiable_cn_numeral_amount"])

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
