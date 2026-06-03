"""FICA and self-employment payroll tax calculations."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .filing import _normalize_filing_status
from .money import _decimal_rule, _money, _money_decimal, _money_quantized
from .responses import _citations, _response
from .rules_loader import load_fica_rules

__all__ = ["fica_tax", "self_employment_tax", "_combined_payroll"]

def fica_tax(wages: float, filing_status: str = "single", tax_year: int = 2026) -> dict[str, Any]:
    """Calculate employee-side FICA tax from stored rules."""

    filing = _normalize_filing_status(filing_status)
    rules = load_fica_rules(tax_year)
    ss = rules["social_security"]
    med = rules["medicare"]
    addl = rules["additional_medicare"]
    wage_amount = max(0.0, float(wages))
    social_security_tax = min(wage_amount, float(ss["wage_base"])) * float(ss["employee_rate"])
    medicare_tax = wage_amount * float(med["employee_rate"])
    threshold = float(addl["taxpayer_thresholds"][filing])
    additional_medicare_tax = max(0.0, wage_amount - threshold) * float(addl["employee_rate"])
    total = social_security_tax + medicare_tax + additional_medicare_tax
    return _response(
        status="ok",
        input_data={
            "wages": wages,
            "filing_status": filing,
            "tax_year": tax_year,
        },
        result={
            "social_security_tax": _money(social_security_tax),
            "medicare_tax": _money(medicare_tax),
            "additional_medicare_tax": _money(additional_medicare_tax),
            "total": _money(total),
        },
        breakdown=[
            {"label": "social_security_tax", "amount": _money(social_security_tax)},
            {"label": "medicare_tax", "amount": _money(medicare_tax)},
            {"label": "additional_medicare_tax", "amount": _money(additional_medicare_tax)},
        ],
        rule_version=rules["rule_version"],
        citations=_citations(ss, med, addl),
        assumptions=[
            "Employee-side FICA only; employer-side taxes are not included.",
            "Additional Medicare Tax uses annual taxpayer filing-status thresholds, "
            "not per-paycheck employer withholding timing.",
        ],
    )

def self_employment_tax(
    net_self_employment_profit: float,
    filing_status: str = "single",
    tax_year: int = 2026,
) -> dict[str, Any]:
    """Calculate self-employment tax using stored FICA rules."""

    filing = _normalize_filing_status(filing_status)
    rules = load_fica_rules(tax_year)
    ss = rules["social_security"]
    med = rules["medicare"]
    addl = rules["additional_medicare"]
    se = rules["self_employment"]

    net_profit = max(Decimal("0"), Decimal(str(net_self_employment_profit)))
    multiplier = _decimal_rule(se["net_earnings_multiplier"])
    base = net_profit * multiplier

    ss_wage_base = _decimal_rule(ss["wage_base"])
    social_security_tax = min(base, ss_wage_base) * _decimal_rule(ss["self_employment_combined_rate"])
    medicare_tax = base * _decimal_rule(med["self_employment_combined_rate"])
    se_tax = social_security_tax + medicare_tax

    threshold = _decimal_rule(addl["taxpayer_thresholds"][filing])
    additional_medicare_tax = max(Decimal("0"), base - threshold) * _decimal_rule(addl["employee_rate"])
    deductible_half_se_tax = se_tax / Decimal("2")
    total = se_tax + additional_medicare_tax

    return _response(
        status="ok",
        input_data={
            "net_self_employment_profit": net_self_employment_profit,
            "filing_status": filing,
            "tax_year": tax_year,
        },
        result={
            "net_earnings_from_self_employment": _money_decimal(base),
            "social_security_tax": _money_decimal(social_security_tax),
            "medicare_tax": _money_decimal(medicare_tax),
            "self_employment_tax": _money_decimal(se_tax),
            "additional_medicare_tax": _money_decimal(additional_medicare_tax),
            "deductible_half_se_tax": _money_decimal(deductible_half_se_tax),
            "total_se_related_tax": _money_decimal(total),
        },
        breakdown=[
            {"label": "net_self_employment_profit", "amount": _money_decimal(net_profit)},
            {"label": "net_earnings_from_self_employment", "amount": _money_decimal(base)},
            {"label": "social_security_tax", "amount": _money_decimal(social_security_tax)},
            {"label": "medicare_tax", "amount": _money_decimal(medicare_tax)},
            {"label": "additional_medicare_tax", "amount": _money_decimal(additional_medicare_tax)},
            {"label": "deductible_half_se_tax", "amount": _money_decimal(deductible_half_se_tax)},
            {"label": "total_se_related_tax", "amount": _money_decimal(total)},
        ],
        rule_version=rules["rule_version"],
        citations=_citations(ss, med, addl, se),
        assumptions=[
            "Self-employment calculation uses stored FICA rules and Decimal arithmetic.",
            "MVP assumes no other W-2 Medicare wages reduce the Additional Medicare threshold.",
            "Deductible half of self-employment tax excludes Additional Medicare Tax.",
        ],
    )

def _combined_payroll(
    w2_wages: Decimal,
    net_self_employment_profit: Decimal,
    filing: str,
    fica_rules: dict[str, Any],
) -> dict[str, Decimal]:
    """Combine W-2 FICA and self-employment tax with shared Social Security base.

    Reuses the caller's already-loaded fica_rules to avoid a second deepcopy on the hot path.
    """

    ss = fica_rules["social_security"]
    med = fica_rules["medicare"]
    addl = fica_rules["additional_medicare"]
    se = fica_rules["self_employment"]

    w2 = max(Decimal("0"), w2_wages)
    net_profit = max(Decimal("0"), net_self_employment_profit)
    se_net_earnings = net_profit * _decimal_rule(se["net_earnings_multiplier"])

    ss_wage_base = _decimal_rule(ss["wage_base"])
    w2_ss_wages = min(w2, ss_wage_base)
    w2_ss = w2_ss_wages * _decimal_rule(ss["employee_rate"])
    remaining_ss_base = max(Decimal("0"), ss_wage_base - w2_ss_wages)
    se_ss_base = min(se_net_earnings, remaining_ss_base)
    se_ss = se_ss_base * _decimal_rule(ss["self_employment_combined_rate"])

    w2_medicare = w2 * _decimal_rule(med["employee_rate"])
    se_medicare = se_net_earnings * _decimal_rule(med["self_employment_combined_rate"])
    self_employment_tax_amount = se_ss + se_medicare

    threshold = _decimal_rule(addl["taxpayer_thresholds"][filing])
    additional_medicare_tax = max(Decimal("0"), (w2 + se_net_earnings) - threshold) * _decimal_rule(
        addl["employee_rate"]
    )
    deductible_half_se_tax = _money_quantized(self_employment_tax_amount / Decimal("2"))
    w2_fica_tax = w2_ss + w2_medicare
    total_payroll_tax = w2_fica_tax + self_employment_tax_amount + additional_medicare_tax

    return {
        "w2_wages": w2,
        "net_self_employment_profit": net_profit,
        "net_earnings_from_self_employment": se_net_earnings,
        "w2_social_security_wages": w2_ss_wages,
        "w2_social_security_tax": w2_ss,
        "w2_medicare_tax": w2_medicare,
        "w2_fica_tax": w2_fica_tax,
        "se_social_security_base": se_ss_base,
        "se_social_security_tax": se_ss,
        "se_medicare_tax": se_medicare,
        "self_employment_tax": self_employment_tax_amount,
        "additional_medicare_tax": additional_medicare_tax,
        "deductible_half_se_tax": deductible_half_se_tax,
        "total_payroll_tax": total_payroll_tax,
    }
