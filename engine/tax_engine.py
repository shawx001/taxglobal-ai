"""Pure tax calculation functions backed by versioned rule JSON."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .rules_loader import (
    load_federal_rules,
    load_feie_rules,
    load_fica_rules,
    load_nexus_rules,
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


def _response(
    *,
    status: str,
    input_data: dict[str, Any],
    result: dict[str, Any] | None,
    breakdown: list[dict[str, Any]],
    rule_version: str,
    citations: list[dict[str, Any]],
    assumptions: list[str] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "input": input_data,
        "result": result,
        "breakdown": breakdown,
        "rule_version": rule_version,
        "citations": citations,
        "assumptions": assumptions or [],
        "reason": reason,
    }


def _not_covered(
    *,
    input_data: dict[str, Any],
    rule_version: str,
    reason: str,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _response(
        status="not_covered",
        input_data=input_data,
        result=None,
        breakdown=[],
        rule_version=rule_version,
        citations=citations or [],
        reason=reason,
    )


def _money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _money_decimal(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _decimal_rule(value: Any) -> Decimal:
    return Decimal(str(value))


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
    return _response(
        status="ok",
        input_data={
            "gross_income": gross_income,
            "filing_status": filing,
            "deduction": deduction_used,
            "tax_year": tax_year,
        },
        result={
            "taxable_income": _money(taxable_income),
            "tax": tax,
        },
        breakdown=[
            {"label": "gross_income", "amount": _money(gross_income)},
            {"label": "deduction", "amount": _money(deduction_used)},
            {"label": "taxable_income", "amount": _money(taxable_income)},
            {"label": "federal_ordinary_income_tax", "amount": tax},
        ],
        rule_version=rules["rule_version"],
        citations=_citations(rules["standard_deduction"], rules["ordinary_income_brackets"]),
        assumptions=[
            "Uses ordinary income brackets only.",
            "Credits, AMT, NIIT, qualified dividends, and capital gain rates are not included in this function.",
        ],
    )


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
            "Additional Medicare Tax uses annual taxpayer filing-status thresholds, not per-paycheck employer withholding timing.",
        ],
    )


def self_employment_tax(
    net_self_employment_profit: float,
    filing_status: str = "single",
    tax_year: int = 2025,
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
            "Self-employment calculation uses stored 2025 FICA rules and Decimal arithmetic.",
            "MVP assumes no other W-2 Medicare wages reduce the Additional Medicare threshold.",
            "Deductible half of self-employment tax excludes Additional Medicare Tax.",
        ],
    )


def feie_estimate(foreign_earned_income: float, days_abroad: int, tax_year: int = 2025) -> dict[str, Any]:
    """Estimate FEIE exclusion eligibility and excluded income."""

    rules = load_feie_rules(tax_year)
    feie = rules["foreign_earned_income_exclusion"]
    income = max(0.0, float(foreign_earned_income))
    required_days = int(feie["physical_presence_days"])
    qualifies = int(days_abroad) >= required_days
    excluded = min(income, float(feie["maximum_exclusion"])) if qualifies else 0.0
    remaining = income - excluded
    return _response(
        status="ok",
        input_data={
            "foreign_earned_income": foreign_earned_income,
            "days_abroad": days_abroad,
            "tax_year": tax_year,
        },
        result={
            "qualifies_physical_presence_test": qualifies,
            "excluded_income": _money(excluded),
            "remaining_income": _money(remaining),
        },
        breakdown=[
            {"label": "foreign_earned_income", "amount": _money(income)},
            {"label": "maximum_exclusion", "amount": _money(feie["maximum_exclusion"])},
            {"label": "excluded_income", "amount": _money(excluded)},
            {"label": "remaining_income", "amount": _money(remaining)},
        ],
        rule_version=rules["rule_version"],
        citations=_citations(feie),
        assumptions=[
            "Only the physical presence day-count rule is evaluated.",
            "Bona fide residence, housing exclusion, FTC, and stacking-rule tax effects are not calculated here.",
        ],
    )


def state_income_tax(state_code: str, taxable_income: float, tax_year: int = 2025) -> dict[str, Any]:
    """Calculate supported state income tax, or explicitly decline unsupported states."""

    rules = load_state_rules(tax_year)
    code = state_code.upper()
    state = rules["states"].get(code)
    if not state:
        return _not_covered(
            input_data={"state": code, "taxable_income": taxable_income, "tax_year": tax_year},
            rule_version=rules["rule_version"],
            reason=f"State {code} is not present in stored 2025 state rules.",
        )

    status = state["status"]
    if status in {"pending_extraction", "source_pending"}:
        return _not_covered(
            input_data={"state": code, "taxable_income": taxable_income, "tax_year": tax_year},
            rule_version=rules["rule_version"],
            citations=_citations(state),
            reason=f"State {code} rule status is {status}; calculation is blocked until sourced and extracted.",
        )
    if status != "effective":
        return _not_covered(
            input_data={"state": code, "taxable_income": taxable_income, "tax_year": tax_year},
            rule_version=rules["rule_version"],
            citations=_citations(state),
            reason=f"State {code} rule status is {status}.",
        )

    tax_type = state["income_tax_type"]
    taxable = max(0.0, float(taxable_income))
    if tax_type in {"flat", "none"}:
        rate = float(state.get("flat_rate", 0.0))
        tax = taxable * rate
        return _response(
            status="ok",
            input_data={"state": code, "taxable_income": taxable_income, "tax_year": tax_year},
            result={
                "state": code,
                "tax": _money(tax),
                "rate": rate,
            },
            breakdown=[
                {"label": "taxable_income", "amount": _money(taxable)},
                {"label": "state_income_tax", "amount": _money(tax)},
            ],
            rule_version=rules["rule_version"],
            citations=_citations(state),
            assumptions=["State-specific deductions and credits are not included."],
        )

    return _not_covered(
        input_data={"state": code, "taxable_income": taxable_income, "tax_year": tax_year},
        rule_version=rules["rule_version"],
        citations=_citations(state),
        reason=f"State {code} income_tax_type {tax_type} is not implemented.",
    )


NEXUS_APPROACHING_RATIO = Decimal("0.80")


def _compare_threshold(value: Decimal, threshold: Decimal, comparison: str) -> bool:
    if comparison == "gt":
        return value > threshold
    if comparison == "gte":
        return value >= threshold
    raise ValueError(f"Unsupported nexus comparison: {comparison}")


def nexus_estimate(
    state_code: str,
    sales_amount: float,
    transaction_count: int | None = None,
    tax_year: int = 2025,
) -> dict[str, Any]:
    """Estimate sales-tax economic nexus from stored state threshold rules."""

    rules = load_nexus_rules(tax_year)
    code = state_code.upper()
    threshold = rules["thresholds"].get(code)
    input_data = {
        "state": code,
        "sales_amount": sales_amount,
        "transaction_count": transaction_count,
        "tax_year": tax_year,
    }

    if not threshold:
        return _not_covered(
            input_data=input_data,
            rule_version=rules["rule_version"],
            reason=f"State {code} is not present in stored 2025 nexus rules.",
        )
    if threshold.get("status") == "source_pending":
        return _not_covered(
            input_data=input_data,
            rule_version=rules["rule_version"],
            citations=_citations(threshold),
            reason=f"State {code} nexus rule status is source_pending; calculation is blocked until sourced.",
        )

    sales_threshold = _decimal_rule(threshold["sales_amount"])
    sales = max(Decimal("0"), Decimal(str(sales_amount)))
    comparison = threshold["comparison"]
    sales_exceeded = _compare_threshold(sales, sales_threshold, comparison)
    sales_approaching = sales >= (sales_threshold * NEXUS_APPROACHING_RATIO)

    tx_threshold_raw = threshold.get("transaction_count")
    tx_threshold = None if tx_threshold_raw is None else Decimal(str(tx_threshold_raw))
    tx_count = None if transaction_count is None else max(0, int(transaction_count))
    tx_exceeded = True
    tx_approaching = False
    assumptions = ["Uses stored state economic nexus thresholds only."]

    if tx_threshold is not None:
        if tx_count is None:
            tx_exceeded = False
            assumptions.append("Transaction count threshold exists but transaction_count input was not provided.")
        else:
            tx_value = Decimal(tx_count)
            tx_exceeded = _compare_threshold(tx_value, tx_threshold, comparison)
            tx_approaching = tx_value >= (tx_threshold * NEXUS_APPROACHING_RATIO)

    if threshold.get("condition") == "amount_and_transactions":
        exceeded = sales_exceeded and tx_exceeded
    else:
        exceeded = sales_exceeded

    approaching = (not exceeded) and (sales_approaching or tx_approaching)
    status_label = "triggered" if exceeded else "approaching" if approaching else "below"

    return _response(
        status="ok",
        input_data=input_data,
        result={
            "state": code,
            "threshold": {
                "sales_amount": _money_decimal(sales_threshold),
                "transaction_count": None if tx_threshold is None else int(tx_threshold),
                "condition": threshold.get("condition", "amount_only"),
                "comparison": comparison,
            },
            "inputs": {
                "sales_amount": _money_decimal(sales),
                "transaction_count": tx_count,
            },
            "exceeded": exceeded,
            "approaching": approaching,
            "status_label": status_label,
        },
        breakdown=[
            {"label": "sales_amount", "amount": _money_decimal(sales)},
            {"label": "sales_threshold", "amount": _money_decimal(sales_threshold)},
        ],
        rule_version=rules["rule_version"],
        citations=_citations(threshold),
        assumptions=assumptions,
    )
