"""Pure tax calculation functions backed by versioned rule JSON."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .rules_loader import (
    load_federal_rules,
    load_feie_rules,
    load_fica_rules,
    load_state_rules,
)


SUPPORTED_FILING_STATUSES = {
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
    "qualifying_surviving_spouse",
}

FILING_ALIASES = {
    "mfj": "married_filing_jointly",
    "mfs": "married_filing_separately",
    "hoh": "head_of_household",
    "qss": "qualifying_surviving_spouse",
}


def _money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _normalize_filing_status(filing_status: str) -> str:
    normalized = FILING_ALIASES.get(filing_status, filing_status)
    if normalized not in SUPPORTED_FILING_STATUSES:
        raise ValueError(f"Unsupported filing_status: {filing_status}")
    return normalized


def _citations(*items: dict[str, Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        citation = item.get("citation")
        for source_id in item.get("source_ids", []):
            key = (source_id, citation or "")
            if key not in seen:
                citations.append({"source_id": source_id, "citation": citation})
                seen.add(key)
    return citations


def bracket_tax(taxable_income: float, brackets: list[dict[str, Any]]) -> float:
    """Calculate marginal bracket tax for non-negative taxable income."""

    taxable = max(0.0, float(taxable_income))
    tax = 0.0
    previous_cap = 0.0
    for bracket in brackets:
        cap = bracket.get("up_to")
        rate = float(bracket["rate"])
        if cap is None:
            tax += max(0.0, taxable - previous_cap) * rate
            break
        cap_float = float(cap)
        if taxable > cap_float:
            tax += (cap_float - previous_cap) * rate
            previous_cap = cap_float
        else:
            tax += max(0.0, taxable - previous_cap) * rate
            break
    return _money(tax)


def federal_income_tax(
    gross_income: float,
    filing_status: str = "single",
    deduction: float | None = None,
    tax_year: int = 2025,
) -> dict[str, Any]:
    """Calculate U.S. federal ordinary income tax from stored rule JSON."""

    filing = _normalize_filing_status(filing_status)
    rules = load_federal_rules(tax_year)
    standard_deduction = rules["standard_deduction"][filing]
    deduction_used = standard_deduction if deduction is None else float(deduction)
    taxable_income = max(0.0, float(gross_income) - deduction_used)
    brackets = rules["ordinary_income_brackets"][filing]
    tax = bracket_tax(taxable_income, brackets)
    return {
        "status": "ok",
        "input": {
            "gross_income": gross_income,
            "filing_status": filing,
            "deduction": deduction_used,
            "tax_year": tax_year,
        },
        "result": {
            "taxable_income": _money(taxable_income),
            "tax": tax,
        },
        "breakdown": [
            {"label": "gross_income", "amount": _money(gross_income)},
            {"label": "deduction", "amount": _money(deduction_used)},
            {"label": "taxable_income", "amount": _money(taxable_income)},
            {"label": "federal_ordinary_income_tax", "amount": tax},
        ],
        "rule_version": rules["rule_version"],
        "citations": _citations(rules["standard_deduction"], rules["ordinary_income_brackets"]),
        "assumptions": [
            "Uses ordinary income brackets only.",
            "Credits, AMT, NIIT, qualified dividends, and capital gain rates are not included in this function.",
        ],
    }


def fica_tax(wages: float, filing_status: str = "single", tax_year: int = 2025) -> dict[str, Any]:
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
    return {
        "status": "ok",
        "input": {
            "wages": wages,
            "filing_status": filing,
            "tax_year": tax_year,
        },
        "result": {
            "social_security_tax": _money(social_security_tax),
            "medicare_tax": _money(medicare_tax),
            "additional_medicare_tax": _money(additional_medicare_tax),
            "total": _money(total),
        },
        "breakdown": [
            {"label": "social_security_tax", "amount": _money(social_security_tax)},
            {"label": "medicare_tax", "amount": _money(medicare_tax)},
            {"label": "additional_medicare_tax", "amount": _money(additional_medicare_tax)},
        ],
        "rule_version": rules["rule_version"],
        "citations": _citations(ss, med, addl),
        "assumptions": ["Employee-side FICA only; employer-side taxes are not included."],
    }


def feie_estimate(foreign_earned_income: float, days_abroad: int, tax_year: int = 2025) -> dict[str, Any]:
    """Estimate FEIE exclusion eligibility and excluded income."""

    rules = load_feie_rules(tax_year)
    feie = rules["foreign_earned_income_exclusion"]
    income = max(0.0, float(foreign_earned_income))
    required_days = int(feie["physical_presence_days"])
    qualifies = int(days_abroad) >= required_days
    excluded = min(income, float(feie["maximum_exclusion"])) if qualifies else 0.0
    remaining = income - excluded
    return {
        "status": "ok",
        "input": {
            "foreign_earned_income": foreign_earned_income,
            "days_abroad": days_abroad,
            "tax_year": tax_year,
        },
        "result": {
            "qualifies_physical_presence_test": qualifies,
            "excluded_income": _money(excluded),
            "remaining_income": _money(remaining),
        },
        "breakdown": [
            {"label": "foreign_earned_income", "amount": _money(income)},
            {"label": "maximum_exclusion", "amount": _money(feie["maximum_exclusion"])},
            {"label": "excluded_income", "amount": _money(excluded)},
            {"label": "remaining_income", "amount": _money(remaining)},
        ],
        "rule_version": rules["rule_version"],
        "citations": _citations(feie),
        "assumptions": [
            "Only the physical presence day-count rule is evaluated.",
            "Bona fide residence, housing exclusion, FTC, and stacking-rule tax effects are not calculated here.",
        ],
    }


def state_income_tax(state_code: str, taxable_income: float, tax_year: int = 2025) -> dict[str, Any]:
    """Calculate supported state income tax, or explicitly decline unsupported states."""

    rules = load_state_rules(tax_year)
    code = state_code.upper()
    state = rules["states"].get(code)
    if not state:
        return {
            "status": "not_covered",
            "input": {"state": code, "taxable_income": taxable_income, "tax_year": tax_year},
            "result": None,
            "breakdown": [],
            "rule_version": rules["rule_version"],
            "citations": [],
            "assumptions": [],
            "reason": f"State {code} is not present in stored 2025 state rules.",
        }

    status = state["status"]
    if status in {"pending_extraction", "source_pending"}:
        return {
            "status": "not_covered",
            "input": {"state": code, "taxable_income": taxable_income, "tax_year": tax_year},
            "result": None,
            "breakdown": [],
            "rule_version": rules["rule_version"],
            "citations": _citations(state),
            "assumptions": [],
            "reason": f"State {code} rule status is {status}; calculation is blocked until sourced and extracted.",
        }
    if status != "effective":
        return {
            "status": "not_covered",
            "input": {"state": code, "taxable_income": taxable_income, "tax_year": tax_year},
            "result": None,
            "breakdown": [],
            "rule_version": rules["rule_version"],
            "citations": _citations(state),
            "assumptions": [],
            "reason": f"State {code} rule status is {status}.",
        }

    tax_type = state["income_tax_type"]
    taxable = max(0.0, float(taxable_income))
    if tax_type in {"flat", "none"}:
        rate = float(state.get("flat_rate", 0.0))
        tax = taxable * rate
        return {
            "status": "ok",
            "input": {"state": code, "taxable_income": taxable_income, "tax_year": tax_year},
            "result": {
                "state": code,
                "tax": _money(tax),
                "rate": rate,
            },
            "breakdown": [
                {"label": "taxable_income", "amount": _money(taxable)},
                {"label": "state_income_tax", "amount": _money(tax)},
            ],
            "rule_version": rules["rule_version"],
            "citations": _citations(state),
            "assumptions": ["State-specific deductions and credits are not included."],
        }

    return {
        "status": "not_covered",
        "input": {"state": code, "taxable_income": taxable_income, "tax_year": tax_year},
        "result": None,
        "breakdown": [],
        "rule_version": rules["rule_version"],
        "citations": _citations(state),
        "assumptions": [],
        "reason": f"State {code} income_tax_type {tax_type} is not implemented.",
    }
