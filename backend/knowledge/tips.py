"""KB-driven tax tips and deadline matching."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

logger = logging.getLogger("taxglobal.knowledge.tips")

_DEFAULT_TAX_YEAR = 2026
_KNOWLEDGE_ROOT = Path(__file__).resolve().parents[2] / "data" / "knowledge" / "us"


@dataclass(frozen=True)
class TipContext:
    """Immutable context for tip matching."""

    state: str = ""
    filing_status: str = "single"
    income_types: tuple[str, ...] = ()
    tax_year: int = _DEFAULT_TAX_YEAR
    gross_income: Decimal = Decimal("0")
    taxable_income: Decimal = Decimal("0")
    w2_wages: Decimal = Decimal("0")
    self_employment_income: Decimal = Decimal("0")
    has_crypto: bool = False
    has_rsu: bool = False
    has_capital_gain: bool = False
    has_investment_income: bool = False
    has_high_income: bool = False


def _load_knowledge(tax_year: int = _DEFAULT_TAX_YEAR) -> list[dict[str, Any]]:
    path = _KNOWLEDGE_ROOT / str(tax_year) / "us_core_knowledge.json"
    if not path.is_file():
        logger.warning("Knowledge file not found: %s", path)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load knowledge items")
        return []
    items = data.get("items", [])
    return items if isinstance(items, list) else []


_KNOWLEDGE_BY_YEAR: dict[int, list[dict[str, Any]]] = {_DEFAULT_TAX_YEAR: _load_knowledge(_DEFAULT_TAX_YEAR)}


def _items_for_year(tax_year: int) -> list[dict[str, Any]]:
    if tax_year not in _KNOWLEDGE_BY_YEAR:
        _KNOWLEDGE_BY_YEAR[tax_year] = _load_knowledge(tax_year)
    return _KNOWLEDGE_BY_YEAR[tax_year]


def _as_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")


def _truthy_amount(data: dict[str, Any], *keys: str) -> bool:
    return any(_as_decimal(data.get(key)) > 0 for key in keys)


def _explicit_income_types(data: dict[str, Any]) -> tuple[str, ...]:
    value = data.get("income_types", ())
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = ()
    return tuple(dict.fromkeys(str(part).strip().lower() for part in parts if str(part).strip()))


def _explicit_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _threshold_value(value: Any, filing_status: str) -> Decimal:
    if isinstance(value, dict):
        return _as_decimal(value.get(filing_status))
    return _as_decimal(value)


def _amount_over_threshold(amount: Decimal, threshold: Any, filing_status: str) -> bool:
    limit = _threshold_value(threshold, filing_status)
    return limit > 0 and amount > limit


def context_from_profile(profile_data: dict[str, Any], tax_year: int = _DEFAULT_TAX_YEAR) -> TipContext:
    """Build TipContext from persisted profile data."""

    state = str(profile_data.get("state") or profile_data.get("state_code") or "").upper()
    filing_status = str(profile_data.get("filing_status") or "single")
    gross_income = _as_decimal(profile_data.get("gross_income"))
    taxable_income = _as_decimal(profile_data.get("taxable_income"))
    w2_wages = _as_decimal(profile_data.get("w2_wages") or profile_data.get("wages"))
    self_employment_income = _as_decimal(
        profile_data.get("self_employment_income") or profile_data.get("net_self_employment_profit")
    )
    income_types: list[str] = list(_explicit_income_types(profile_data))
    if _truthy_amount(profile_data, "w2_wages", "wages"):
        income_types.append("w2")
    if _truthy_amount(profile_data, "self_employment_income", "net_self_employment_profit"):
        income_types.append("self_employment")
    if _truthy_amount(profile_data, "foreign_earned_income"):
        income_types.append("foreign")
    has_crypto = bool(profile_data.get("crypto_transactions") or profile_data.get("crypto_lots"))
    has_rsu = bool(profile_data.get("rsu_vests") or profile_data.get("rsu_grants"))
    has_capital_gain = _truthy_amount(profile_data, "long_term_capital_gain", "short_term_capital_gain")
    has_investment_income = has_capital_gain or _truthy_amount(profile_data, "investment_income", "dividends")
    has_high_income = "high_income" in income_types or _explicit_bool(profile_data.get("high_income"))
    if has_crypto:
        income_types.append("crypto")
    if has_rsu:
        income_types.append("rsu")
    if has_capital_gain:
        income_types.append("capital_gain")
    if has_investment_income:
        income_types.append("investment")
    if has_high_income:
        income_types.append("high_income")
    deduped = tuple(dict.fromkeys(income_types))
    return TipContext(
        state=state,
        filing_status=filing_status,
        income_types=deduped,
        tax_year=tax_year,
        gross_income=gross_income,
        taxable_income=taxable_income,
        w2_wages=w2_wages,
        self_employment_income=self_employment_income,
        has_crypto=has_crypto,
        has_rsu=has_rsu,
        has_capital_gain=has_capital_gain,
        has_investment_income=has_investment_income,
        has_high_income=has_high_income,
    )


def context_from_params(
    state: str = "",
    filing_status: str = "single",
    income_types: str = "",
    tax_year: int = _DEFAULT_TAX_YEAR,
) -> TipContext:
    """Build TipContext from direct query params."""

    types = tuple(dict.fromkeys(part.strip().lower() for part in income_types.split(",") if part.strip()))
    return TipContext(
        state=state.upper(),
        filing_status=filing_status,
        income_types=types,
        tax_year=tax_year,
        has_crypto="crypto" in types,
        has_rsu="rsu" in types,
        has_capital_gain="capital_gain" in types or "long_term_capital_gain" in types,
        has_investment_income="investment" in types or "capital_gain" in types or "long_term_capital_gain" in types,
        has_high_income="high_income" in types,
    )


def _jurisdiction_matches(item: dict[str, Any], ctx: TipContext) -> bool:
    jurisdiction = str(item.get("jurisdiction", "")).upper()
    return jurisdiction == "US" or not ctx.state or jurisdiction == ctx.state


def _condition_matches(key: str, value: Any, ctx: TipContext) -> bool:
    if key == "tax_year":
        return int(value) == ctx.tax_year
    if key == "state":
        return str(value).upper() == ctx.state
    if key == "filing_status":
        return str(value) == ctx.filing_status
    if key in {"self_employment_income", "qualified_business_income"}:
        return "self_employment" in ctx.income_types
    if key in {"foreign_earned_income", "foreign_earned_income_present", "taxpayer_abroad"}:
        return "foreign" in ctx.income_types
    if key in {"w2_wages", "wages"}:
        return "w2" in ctx.income_types
    if key == "earned_income":
        return "w2" in ctx.income_types or "self_employment" in ctx.income_types
    if key in {"digital_asset_sale", "staking_rewards", "nft_sale", "digital_asset_broker_reporting"}:
        return ctx.has_crypto
    if key in {"rsu_vesting", "rsu_sale"}:
        return ctx.has_rsu
    if key == "estimated_tax_required":
        return "self_employment" in ctx.income_types
    if key == "high_income":
        return ctx.has_high_income or "high_income" in ctx.income_types
    if key == "taxable_income_over":
        return _amount_over_threshold(ctx.taxable_income, value, ctx.filing_status)
    if key == "wages_or_self_employment_income_over":
        income = ctx.w2_wages + ctx.self_employment_income
        return _amount_over_threshold(income, value, ctx.filing_status)
    if key == "net_self_employment_income_over":
        return _amount_over_threshold(ctx.self_employment_income, value, ctx.filing_status)
    if key in {"deadline_type", "estimated_tax_installment", "extension_requested", "information_return"}:
        return True
    if key in {"days_abroad_required", "foreign_housing_expenses", "foreign_taxes_paid"}:
        return "foreign" in ctx.income_types
    if key in {"long_term_capital_gain", "capital_gain"}:
        return (
            ctx.has_capital_gain
            or "capital_gain" in ctx.income_types
            or "long_term_capital_gain" in ctx.income_types
        )
    if key == "investment_income":
        return ctx.has_investment_income or "investment" in ctx.income_types
    if isinstance(value, bool):
        return bool(value) and key in ctx.income_types
    return False


def _matches_trigger(trigger: dict[str, Any], ctx: TipContext) -> bool:
    if not trigger:
        return True
    for key, value in trigger.items():
        if not _condition_matches(key, value, ctx):
            return False
    return True


def _topic_matches_income(topic: str, ctx: TipContext) -> bool:
    topic_lower = topic.lower()
    return (
        ("self_employment" in ctx.income_types and ("self_employment" in topic_lower or topic_lower == "qbi"))
        or ("foreign" in ctx.income_types and ("foreign" in topic_lower or "feie" in topic_lower))
        or ("w2" in ctx.income_types and topic_lower in {"payroll_tax", "federal_income_tax"})
        or (ctx.has_crypto and ("crypto" in topic_lower or "capital_gains" in topic_lower))
        or (ctx.has_rsu and ("rsu" in topic_lower or "stock" in topic_lower))
    )


def _deadline_date(item: dict[str, Any], ctx: TipContext) -> str:
    trigger = item.get("trigger_conditions", {})
    if not isinstance(trigger, dict):
        trigger = {}
    month_day = ("04", "15")
    if trigger.get("estimated_tax_installment") == "q2" or trigger.get("taxpayer_abroad"):
        month_day = ("06", "15")
    elif trigger.get("estimated_tax_installment") == "q3":
        month_day = ("09", "15")
    elif trigger.get("estimated_tax_installment") == "q4":
        return date(ctx.tax_year + 1, 1, 15).isoformat()
    elif trigger.get("extension_requested"):
        month_day = ("10", "15")
    elif trigger.get("information_return") in {"w2", "1099"}:
        month_day = ("01", "31")
    return f"{ctx.tax_year}-{month_day[0]}-{month_day[1]}"


def _relevance_score(item: dict[str, Any], ctx: TipContext) -> float:
    score = 0.3 if item.get("jurisdiction") == "US" else 0.2
    if ctx.state and str(item.get("jurisdiction", "")).upper() == ctx.state:
        score += 0.3
    if _topic_matches_income(str(item.get("topic", "")), ctx):
        score += 0.3
    if item.get("topic") == "deadline":
        score += 0.2
    if item.get("source_ids"):
        score += 0.1
    trigger = item.get("trigger_conditions", {})
    if isinstance(trigger, dict) and any(key in trigger for key in ("high_income", "taxable_income_over")):
        score -= 0.05
    return round(max(0.0, min(1.0, score)), 3)


def _tip_payload(item: dict[str, Any], ctx: TipContext) -> dict[str, Any]:
    return {
        "knowledge_id": item.get("knowledge_id", ""),
        "title": item.get("title") or item.get("topic", ""),
        "topic": item.get("topic", ""),
        "summary": item.get("summary", ""),
        "jurisdiction": item.get("jurisdiction", ""),
        "relevance": _relevance_score(item, ctx),
        "sources": list(item.get("source_ids", [])),
    }


def get_tips(ctx: TipContext, *, max_tips: int = 10) -> list[dict[str, Any]]:
    """Return ranked non-deadline tips matching the context."""

    matched: list[dict[str, Any]] = []
    for item in _items_for_year(ctx.tax_year):
        if item.get("topic") == "deadline" or not _jurisdiction_matches(item, ctx):
            continue
        trigger = item.get("trigger_conditions", {})
        if isinstance(trigger, dict) and _matches_trigger(trigger, ctx):
            matched.append(_tip_payload(item, ctx))
    matched.sort(key=lambda tip: (-float(tip["relevance"]), str(tip["knowledge_id"])))
    return matched[: max(0, max_tips)]


def _deadline_matches(item: dict[str, Any], ctx: TipContext) -> bool:
    trigger = item.get("trigger_conditions", {})
    if not isinstance(trigger, dict):
        return True
    if trigger.get("estimated_tax_installment"):
        return "self_employment" in ctx.income_types
    if trigger.get("taxpayer_abroad"):
        return "foreign" in ctx.income_types
    if trigger.get("information_return") == "w2":
        return "w2" in ctx.income_types or not ctx.income_types
    if trigger.get("information_return") == "1099":
        return "self_employment" in ctx.income_types or not ctx.income_types
    return bool(trigger.get("deadline_type") == "filing" or trigger.get("extension_requested"))


def get_deadlines(ctx: TipContext) -> list[dict[str, Any]]:
    """Return deadlines matching the context, sorted by date."""

    deadlines: list[dict[str, Any]] = []
    for item in _items_for_year(ctx.tax_year):
        if item.get("topic") != "deadline" or not _jurisdiction_matches(item, ctx) or not _deadline_matches(item, ctx):
            continue
        deadlines.append(
            {
                "knowledge_id": item.get("knowledge_id", ""),
                "title": item.get("title") or item.get("topic", ""),
                "date": _deadline_date(item, ctx),
                "summary": item.get("summary", ""),
                "applies_to": item.get("jurisdiction", "US"),
                "sources": list(item.get("source_ids", [])),
            }
        )
    deadlines.sort(key=lambda item: (item["date"], item["knowledge_id"]))
    return deadlines
