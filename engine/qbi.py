"""Section 199A QBI deduction calculation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .filing import _normalize_filing_status
from .money import _decimal_input, _decimal_rule, _money_decimal
from .responses import _citations, _invalid_input, _response
from .rules_loader import load_qbi_rules

__all__ = ["qbi_deduction"]

def qbi_deduction(
    qbi: float,
    taxable_income: float,
    filing_status: str = "single",
    net_capital_gain: float = 0.0,
    w2_wages: float = 0.0,
    ubia: float = 0.0,
    is_sstb: bool = False,
    tax_year: int = 2026,
) -> dict[str, Any]:
    """Calculate the Section 199A QBI deduction from stored rule data."""

    raw_input = {
        "qbi": qbi,
        "taxable_income": taxable_income,
        "filing_status": filing_status,
        "net_capital_gain": net_capital_gain,
        "w2_wages": w2_wages,
        "ubia": ubia,
        "is_sstb": is_sstb,
        "tax_year": tax_year,
    }

    rules = load_qbi_rules(tax_year)
    qbi_rules = rules["qbi_deduction"]
    citations = _citations(qbi_rules, qbi_rules.get("wage_ubia_limit", {}))

    try:
        filing = _normalize_filing_status(filing_status)
        qbi_amount = max(Decimal("0"), _decimal_input(qbi, "qbi"))
        taxable = max(Decimal("0"), _decimal_input(taxable_income, "taxable_income"))
        net_capital_gain_amount = max(Decimal("0"), _decimal_input(net_capital_gain, "net_capital_gain"))
        w2_wages_amount = max(Decimal("0"), _decimal_input(w2_wages, "w2_wages"))
        ubia_amount = max(Decimal("0"), _decimal_input(ubia, "ubia"))
    except ValueError as exc:
        return _invalid_input(
            input_data=raw_input,
            rule_version=rules["rule_version"],
            reason=str(exc),
            citations=citations,
        )

    rate = _decimal_rule(qbi_rules["rate"])
    threshold = _decimal_rule(qbi_rules["taxable_income_threshold"][filing])
    phase_in_window = _decimal_rule(qbi_rules["phase_in_window"][filing])
    upper_limit = _decimal_rule(qbi_rules["upper_limit"][filing])
    wage_ubia_rules = qbi_rules["wage_ubia_limit"]

    tentative = rate * qbi_amount
    overall_limit = rate * max(Decimal("0"), taxable - net_capital_gain_amount)
    wage_ubia_limit = max(
        _decimal_rule(wage_ubia_rules["half_w2_wages_rate"]) * w2_wages_amount,
        _decimal_rule(wage_ubia_rules["quarter_w2_wages_rate"]) * w2_wages_amount
        + _decimal_rule(wage_ubia_rules["ubia_rate"]) * ubia_amount,
    )

    threshold_band: str
    applied_limit: str
    qbi_component: Decimal

    if taxable <= threshold:
        threshold_band = "below_threshold"
        qbi_component = tentative
        applied_limit = "below_threshold"
    elif taxable >= upper_limit:
        threshold_band = "above_upper_limit"
        if is_sstb:
            qbi_component = Decimal("0")
            applied_limit = "sstb_excluded"
        else:
            qbi_component = min(tentative, wage_ubia_limit)
            applied_limit = "wage_ubia_limited"
    else:
        threshold_band = "phase_in"
        ratio = (taxable - threshold) / phase_in_window
        if is_sstb:
            applicable_percentage = Decimal("1") - ratio
            applicable_qbi = qbi_amount * applicable_percentage
            applicable_w2_wages = w2_wages_amount * applicable_percentage
            applicable_ubia = ubia_amount * applicable_percentage
            applicable_tentative = rate * applicable_qbi
            applicable_wage_ubia_limit = max(
                _decimal_rule(wage_ubia_rules["half_w2_wages_rate"]) * applicable_w2_wages,
                _decimal_rule(wage_ubia_rules["quarter_w2_wages_rate"]) * applicable_w2_wages
                + _decimal_rule(wage_ubia_rules["ubia_rate"]) * applicable_ubia,
            )
            excess = max(Decimal("0"), applicable_tentative - applicable_wage_ubia_limit)
            qbi_component = applicable_tentative - (excess * ratio)
        else:
            excess = max(Decimal("0"), tentative - wage_ubia_limit)
            qbi_component = tentative - (excess * ratio)
        applied_limit = "phase_in"

    deduction = min(qbi_component, overall_limit)
    if applied_limit != "sstb_excluded" and deduction < qbi_component:
        applied_limit = "overall_income_capped"

    return _response(
        status="ok",
        input_data={
            "qbi": _money_decimal(qbi_amount),
            "taxable_income": _money_decimal(taxable),
            "filing_status": filing,
            "net_capital_gain": _money_decimal(net_capital_gain_amount),
            "w2_wages": _money_decimal(w2_wages_amount),
            "ubia": _money_decimal(ubia_amount),
            "is_sstb": bool(is_sstb),
            "tax_year": tax_year,
        },
        result={
            "deduction": _money_decimal(deduction),
            "qbi_component": _money_decimal(qbi_component),
            "overall_limit": _money_decimal(overall_limit),
            "applied_limit": applied_limit,
            "threshold_band": threshold_band,
        },
        breakdown=[
            {"label": "qbi", "amount": _money_decimal(qbi_amount)},
            {"label": "tentative_qbi_deduction", "amount": _money_decimal(tentative)},
            {"label": "overall_limit", "amount": _money_decimal(overall_limit)},
            {"label": "wage_ubia_limit", "amount": _money_decimal(wage_ubia_limit)},
            {"label": "qbi_component", "amount": _money_decimal(qbi_component)},
            {"label": "deduction", "amount": _money_decimal(deduction)},
        ],
        rule_version=rules["rule_version"],
        citations=citations,
        assumptions=[
            "Negative QBI, taxable income, net capital gain, W-2 wages, and UBIA inputs are clamped to zero.",
            "W-2 wages, UBIA, and SSTB status default to 0, 0, and False; callers must provide "
            "entity-specific values above the threshold.",
            "SSTB industry classification and UBIA eligibility are not determined by this function.",
            "SSTB and phase-in calculations are complex; professional review is recommended for high-income "
            "or mixed-business cases.",
            "REIT dividends and publicly traded partnership income under Section 199A are outside this function.",
        ],
    )
