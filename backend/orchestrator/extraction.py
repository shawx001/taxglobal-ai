"""LLM parameter extraction (2026-06-11, replaces regex when LLM is on).

The regex extractor mis-reads natural language ("我有W2" became
w2_wages=2.00). When ENABLE_LLM is on, the LLM extracts ONLY the values
the user explicitly stated, as strict JSON, and every field is
defensively validated here — amounts through Decimal, days through
range checks. Any failure returns None and the caller falls back to the
regex extractor, which remains the ENABLE_LLM=false path.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger("taxglobal.orchestrator")

_MAX_EXTRACTION_TOKENS = 256
_MAX_AMOUNT = Decimal("999999999.99")

# Same hardening decisions as backend/llm/vision.py: commas stripped only
# for valid thousands grouping; leading-zero integers are identifiers.
_THOUSANDS_GROUPED = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")

# Per-intent field specs: name -> kind (amount | days | state | count).
_INTENT_FIELDS: dict[str, dict[str, str]] = {
    "income_tax": {
        "w2_wages": "amount",
        "net_self_employment_profit": "amount",
        "state_code": "state",
    },
    "feie": {
        "foreign_earned_income": "amount",
        "days_abroad": "days",
    },
    "nexus": {
        "state_code": "state",
        "sales_amount": "amount",
        "transaction_count": "count",
    },
}

_EXTRACTION_SYSTEM_PROMPT = """\
You extract tax-calculation inputs from a user's message.

Rules:
1. Extract ONLY values the user explicitly stated. If a value is not
   stated, it MUST be null. NEVER guess, NEVER fill defaults.
2. Mentioning a form name is NOT an amount: "我有W2" states no wage.
3. Normalize: "20w"/"20万" -> 200000; "100,000" -> 100000. Months stated
   as a duration may be converted to approximate days (10个月 -> 300).
4. US states map to 2-letter codes (加州 -> CA, 纽约 -> NY).
5. Respond with ONLY a JSON object of the requested fields, no markdown.
"""


def _clean_amount(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("$", "").strip()
    if not text:
        return None
    if "," in text:
        if not _THOUSANDS_GROUPED.match(text):
            return None
        text = text.replace(",", "")
    if len(text) > 1 and text.startswith("0") and "." not in text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    # Zero is rejected DELIBERATELY (engine schemas allow ge=0, but LLMs
    # routinely return 0 instead of null for values the user never stated
    # — accepting 0 would compute a confident $0 answer for "我有W2").
    # A user who genuinely means zero gets one clarifying question; a
    # fabricated zero never becomes a wrong tax bill.
    if not amount.is_finite() or amount <= 0 or amount > _MAX_AMOUNT:
        return None
    return format(amount.normalize(), "f")


def _clean_days(value: Any) -> int | None:
    try:
        days = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    if days < 0 or days > 366:
        return None
    return days


def _clean_count(value: Any) -> int | None:
    try:
        count = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    if count < 0 or count > 100_000_000:
        return None
    return count


def _clean_state(value: Any) -> str | None:
    if value is None:
        return None
    state = str(value).strip().upper()
    if len(state) == 2 and state.isascii() and state.isalpha():
        return state
    return None


_CLEANERS = {"amount": _clean_amount, "days": _clean_days, "count": _clean_count, "state": _clean_state}


def llm_extract_params(query: str, intent: str) -> dict[str, Any] | None:
    """Extract skill parameters with the LLM.

    Returns a dict of validated fields (possibly empty = user stated
    nothing), or ``None`` on any failure so the caller falls back to the
    regex extractor.
    """

    fields = _INTENT_FIELDS.get(intent)
    if not fields:
        return None

    from backend.llm.client import get_provider
    from backend.llm.provider import LLMMessage

    provider = get_provider()
    if provider is None:
        return None

    field_lines = "\n".join(f"- {name} ({kind})" for name, kind in fields.items())
    user_content = f"FIELDS:\n{field_lines}\n\nMESSAGE:\n{query}"
    messages = [
        LLMMessage(role="system", content=_EXTRACTION_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_content),
    ]

    try:
        response = provider.complete(messages, temperature=0.0, max_tokens=_MAX_EXTRACTION_TOKENS)
    except Exception:
        logger.exception("LLM param extraction failed, falling back to regex")
        return None
    if response is None:
        return None

    content = response.content if isinstance(response.content, str) else ""
    try:
        parsed = json.loads(content.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None

    extracted: dict[str, Any] = {}
    for name, kind in fields.items():
        if name not in parsed or parsed[name] is None:
            continue
        cleaned = _CLEANERS[kind](parsed[name])
        if cleaned is not None:
            extracted[name] = cleaned
    return extracted
