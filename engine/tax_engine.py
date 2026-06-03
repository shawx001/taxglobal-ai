"""Pure tax calculation functions backed by versioned rule JSON."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .rules_loader import (
    load_capital_gains_rules,
    load_federal_rules,
    load_feie_rules,
    load_fica_rules,
    load_nexus_rules,
    load_qbi_rules,
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


def _invalid_input(
    *,
    input_data: dict[str, Any],
    rule_version: str,
    reason: str,
    citations: list[dict[str, Any]] | None = None,
    assumptions: list[str] | None = None,
) -> dict[str, Any]:
    return _response(
        status="invalid_input",
        input_data=input_data,
        result=None,
        breakdown=[],
        rule_version=rule_version,
        citations=citations or [],
        assumptions=assumptions,
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


def _merge_citations(*citation_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for citation_list in citation_lists:
        for citation in citation_list:
            key = (citation.get("source_id", ""), citation.get("citation", ""))
            if key not in seen:
                citations.append(citation)
                seen.add(key)
    return citations


def _bracket_tax_decimal(taxable_income: Decimal, brackets: list[dict[str, Any]]) -> Decimal:
    taxable = max(Decimal("0"), taxable_income)
    tax = Decimal("0")
    previous_cap = Decimal("0")
    for bracket in brackets:
        cap = bracket.get("up_to")
        rate = _decimal_rule(bracket["rate"])
        if cap is None:
            tax += max(Decimal("0"), taxable - previous_cap) * rate
            break
        cap_decimal = _decimal_rule(cap)
        if taxable > cap_decimal:
            tax += (cap_decimal - previous_cap) * rate
            previous_cap = cap_decimal
        else:
            tax += max(Decimal("0"), taxable - previous_cap) * rate
            break
    return tax


def _parse_iso_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date string") from exc


def _add_one_calendar_year(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, day=28)


def _decimal_input(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field_name} must be numeric") from exc


def _summary_rule_version(
    tax_year: int,
    federal_rules: dict[str, Any],
    fica_rules: dict[str, Any],
    qbi_rules: dict[str, Any],
    state_rules: dict[str, Any],
) -> str:
    return (
        f"us-{tax_year}-income-summary-v0.1+"
        f"{federal_rules['rule_version']}+{fica_rules['rule_version']}+"
        f"{qbi_rules['rule_version']}+{state_rules['rule_version']}"
    )


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
            "Additional Medicare Tax uses annual taxpayer filing-status thresholds, "
            "not per-paycheck employer withholding timing.",
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


def qbi_deduction(
    qbi: float,
    taxable_income: float,
    filing_status: str = "single",
    net_capital_gain: float = 0.0,
    w2_wages: float = 0.0,
    ubia: float = 0.0,
    is_sstb: bool = False,
    tax_year: int = 2025,
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


def state_income_tax(
    state_code: str,
    taxable_income: float,
    filing_status: str = "single",
    tax_year: int = 2025,
) -> dict[str, Any]:
    """Calculate supported state income tax, or explicitly decline unsupported states."""

    rules = load_state_rules(tax_year)
    code = state_code.upper()
    state = rules["states"].get(code)
    input_data = {
        "state": code,
        "taxable_income": taxable_income,
        "filing_status": filing_status,
        "tax_year": tax_year,
    }
    if not state:
        return _not_covered(
            input_data=input_data,
            rule_version=rules["rule_version"],
            reason=f"State {code} is not present in stored 2025 state rules.",
        )

    status = state["status"]
    if status in {"pending_extraction", "source_pending"}:
        return _not_covered(
            input_data=input_data,
            rule_version=rules["rule_version"],
            citations=_citations(state),
            reason=f"State {code} rule status is {status}; calculation is blocked until sourced and extracted.",
        )
    if status != "effective":
        return _not_covered(
            input_data=input_data,
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
            input_data=input_data,
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

    if tax_type == "progressive":
        filing = _normalize_filing_status(filing_status)
        tax = bracket_tax(taxable, state["brackets"][filing])
        return _response(
            status="ok",
            input_data={**input_data, "filing_status": filing},
            result={
                "state": code,
                "tax": tax,
                "income_tax_type": "progressive",
            },
            breakdown=[
                {"label": "taxable_income", "amount": _money(taxable)},
                {"label": "state_income_tax", "amount": tax},
            ],
            rule_version=rules["rule_version"],
            citations=_citations(state),
            assumptions=[
                "State-specific deductions and credits are not included.",
                state["notes"],
            ],
        )

    return _not_covered(
        input_data=input_data,
        rule_version=rules["rule_version"],
        citations=_citations(state),
        reason=f"State {code} income_tax_type {tax_type} is not implemented.",
    )


def _state_taxable_base(
    state_block: dict[str, Any],
    *,
    federal_agi: Decimal,
    federal_taxable_income: Decimal,
    federal_qbi_deduction: Decimal,
    filing: str,
) -> Decimal:
    """Calculate state taxable base from stored state tax_base data."""

    tax_base = state_block.get("tax_base")
    if tax_base is None:
        return federal_taxable_income

    start_from = tax_base["start_from"]
    if start_from == "federal_taxable_income":
        addback = federal_qbi_deduction if tax_base.get("qbi_addback") else Decimal("0")
        return max(Decimal("0"), federal_taxable_income + addback)

    if start_from != "federal_agi":
        raise ValueError(f"Unsupported state tax_base start_from: {start_from}")

    if tax_base.get("uses_exemption_allowance"):
        exemption_count = Decimal("2") if filing == "married_filing_jointly" else Decimal("1")
        phaseout = _decimal_rule(tax_base["exemption_phaseout_agi"][filing])
        allowance = Decimal("0")
        if federal_agi <= phaseout:
            allowance = _decimal_rule(tax_base["exemption_allowance_per_person"]) * exemption_count
        return max(Decimal("0"), federal_agi - allowance)

    standard_deduction = _decimal_rule(tax_base["standard_deduction"][filing])
    return max(Decimal("0"), federal_agi - standard_deduction)


def income_tax_summary(
    net_self_employment_profit: float = 0.0,
    other_ordinary_income: float = 0.0,
    filing_status: str = "single",
    state_code: str | None = None,
    se_health_insurance: float = 0.0,
    retirement_contributions: float = 0.0,
    qbi_w2_wages: float = 0.0,
    qbi_ubia: float = 0.0,
    is_sstb: bool = False,
    deduction: float | None = None,
    tax_year: int = 2025,
) -> dict[str, Any]:
    """Combine self-employment, QBI, federal, and state income tax for self-employment income."""

    raw_input = {
        "net_self_employment_profit": net_self_employment_profit,
        "other_ordinary_income": other_ordinary_income,
        "filing_status": filing_status,
        "state_code": None if state_code is None else state_code.upper(),
        "se_health_insurance": se_health_insurance,
        "retirement_contributions": retirement_contributions,
        "qbi_w2_wages": qbi_w2_wages,
        "qbi_ubia": qbi_ubia,
        "is_sstb": is_sstb,
        "deduction": deduction,
        "tax_year": tax_year,
    }
    federal_rules = load_federal_rules(tax_year)
    fica_rules = load_fica_rules(tax_year)
    qbi_rules = load_qbi_rules(tax_year)
    state_rules = load_state_rules(tax_year)
    rule_version = _summary_rule_version(tax_year, federal_rules, fica_rules, qbi_rules, state_rules)

    base_citations = _merge_citations(
        _citations(federal_rules["standard_deduction"], federal_rules["ordinary_income_brackets"]),
        _citations(
            fica_rules["social_security"],
            fica_rules["medicare"],
            fica_rules["additional_medicare"],
            fica_rules["self_employment"],
        ),
        _citations(qbi_rules["qbi_deduction"], qbi_rules["qbi_deduction"].get("wage_ubia_limit", {})),
    )

    try:
        filing = _normalize_filing_status(filing_status)
        net_profit = max(Decimal("0"), _decimal_input(net_self_employment_profit, "net_self_employment_profit"))
        other_income = max(Decimal("0"), _decimal_input(other_ordinary_income, "other_ordinary_income"))
        health_insurance = max(Decimal("0"), _decimal_input(se_health_insurance, "se_health_insurance"))
        retirement = max(Decimal("0"), _decimal_input(retirement_contributions, "retirement_contributions"))
        w2_wages = max(Decimal("0"), _decimal_input(qbi_w2_wages, "qbi_w2_wages"))
        ubia = max(Decimal("0"), _decimal_input(qbi_ubia, "qbi_ubia"))
        deduction_used = (
            _decimal_rule(federal_rules["standard_deduction"][filing])
            if deduction is None
            else max(Decimal("0"), _decimal_input(deduction, "deduction"))
        )
    except ValueError as exc:
        return _invalid_input(
            input_data=raw_input,
            rule_version=rule_version,
            reason=str(exc),
            citations=base_citations,
        )

    se_result = self_employment_tax(net_profit, filing, tax_year)
    se_tax = _decimal_rule(se_result["result"]["self_employment_tax"])
    additional_medicare_tax = _decimal_rule(se_result["result"]["additional_medicare_tax"])
    deductible_half_se_tax = _decimal_rule(se_result["result"]["deductible_half_se_tax"])

    above_line_deductions = deductible_half_se_tax + health_insurance + retirement
    adjusted_gross_income = max(Decimal("0"), net_profit + other_income - above_line_deductions)
    taxable_before_qbi = max(Decimal("0"), adjusted_gross_income - deduction_used)
    qbi_amount = max(Decimal("0"), adjusted_gross_income - other_income)

    qbi_result = qbi_deduction(
        qbi=qbi_amount,
        taxable_income=taxable_before_qbi,
        filing_status=filing,
        w2_wages=w2_wages,
        ubia=ubia,
        is_sstb=is_sstb,
        tax_year=tax_year,
    )
    if qbi_result["status"] != "ok":
        return _invalid_input(
            input_data={**raw_input, "filing_status": filing},
            rule_version=rule_version,
            reason=f"QBI deduction failed: {qbi_result['reason']}",
            citations=_merge_citations(base_citations, qbi_result["citations"]),
            assumptions=qbi_result["assumptions"],
        )
    qbi_deduction_amount = _decimal_rule(qbi_result["result"]["deduction"])

    taxable_income = max(Decimal("0"), taxable_before_qbi - qbi_deduction_amount)
    federal_income_tax_amount = _bracket_tax_decimal(
        taxable_income,
        federal_rules["ordinary_income_brackets"][filing],
    )

    state_taxable_base = taxable_income
    state_result = None
    state_tax = Decimal("0")
    state_income_tax_result: dict[str, Any] | None = None
    state_citations: list[dict[str, Any]] = []
    normalized_state_code = None if state_code is None else state_code.upper()

    if normalized_state_code:
        state_block = state_rules["states"].get(normalized_state_code)
        state_tax_base_citations = _citations(state_block.get("tax_base", {})) if state_block else []
        if (
            state_block
            and state_block.get("status") == "effective"
            and state_block.get("income_tax_type") in {"flat", "progressive"}
        ):
            try:
                state_taxable_base = _state_taxable_base(
                    state_block,
                    federal_agi=adjusted_gross_income,
                    federal_taxable_income=taxable_income,
                    federal_qbi_deduction=qbi_deduction_amount,
                    filing=filing,
                )
            except ValueError as exc:
                return _invalid_input(
                    input_data={**raw_input, "filing_status": filing},
                    rule_version=rule_version,
                    reason=str(exc),
                    citations=base_citations,
                )

        state_result = state_income_tax(normalized_state_code, state_taxable_base, filing, tax_year)
        state_citations = _merge_citations(state_result["citations"], state_tax_base_citations)
        if state_result["status"] == "ok":
            state_tax = _decimal_rule(state_result["result"]["tax"])
            state_income_tax_result = {
                **state_result["result"],
                "status": "ok",
            }
        else:
            state_income_tax_result = {
                "status": state_result["status"],
                "not_covered": True,
                "tax": 0.00,
                "reason": state_result["reason"],
            }

    total_tax = se_tax + additional_medicare_tax + federal_income_tax_amount + state_tax
    quarterly_estimate = total_tax / Decimal("4")

    assumptions = [
        "Self-employment summary combines stored SE tax, QBI, federal ordinary income, and state income tax rules.",
        "State taxable bases use stored tax_base data for start point, state standard deduction or exemption "
        "allowance, and QBI conformity where available.",
        "State-specific residual adjustments are not modeled, including NY tax benefit recapture above $107,650 "
        "NYAGI, IL/GA retirement subtractions, CA Schedule CA adjustments, age/blind additional amounts, "
        "state credits, and dependent-specific IL exemption counts.",
        "NIIT is not applied to active self-employment income in this summary.",
        "Self-employment health insurance and retirement contributions are caller-provided above-line deductions.",
    ]
    if state_result is not None and state_result["status"] != "ok":
        assumptions.append(
            "State income tax is not covered for the requested state; total tax includes federal and SE tax only."
        )
    if normalized_state_code == "IL":
        assumptions.append(
            "Illinois exemption allowance assumes MFJ has two exemptions and all other filing statuses have one."
        )
    if normalized_state_code == "CO" and state_result is not None and state_result["status"] == "ok":
        assumptions.append(
            "Colorado QBI addback is applied from stored tax_base data, but Colorado-specific statutory conditions "
            "for that addback are not fully modeled in this summary."
        )

    result = {
        "self_employment_tax": _money_decimal(se_tax),
        "additional_medicare_tax": _money_decimal(additional_medicare_tax),
        "deductible_half_se_tax": _money_decimal(deductible_half_se_tax),
        "adjusted_gross_income": _money_decimal(adjusted_gross_income),
        "deduction_used": _money_decimal(deduction_used),
        "taxable_before_qbi": _money_decimal(taxable_before_qbi),
        "qbi_deduction": _money_decimal(qbi_deduction_amount),
        "taxable_income": _money_decimal(taxable_income),
        "state_taxable_base": None if normalized_state_code is None else _money_decimal(state_taxable_base),
        "state_income_tax": state_income_tax_result,
        "federal_income_tax": _money_decimal(federal_income_tax_amount),
        "total_tax": _money_decimal(total_tax),
        "quarterly_estimate": _money_decimal(quarterly_estimate),
    }

    return _response(
        status="ok",
        input_data={
            **raw_input,
            "filing_status": filing,
            "net_self_employment_profit": _money_decimal(net_profit),
            "other_ordinary_income": _money_decimal(other_income),
            "se_health_insurance": _money_decimal(health_insurance),
            "retirement_contributions": _money_decimal(retirement),
            "qbi_w2_wages": _money_decimal(w2_wages),
            "qbi_ubia": _money_decimal(ubia),
            "deduction": _money_decimal(deduction_used),
        },
        result=result,
        breakdown=[
            {"label": "net_self_employment_profit", "amount": _money_decimal(net_profit)},
            {"label": "deductible_half_se_tax", "amount": _money_decimal(deductible_half_se_tax)},
            {"label": "above_line_deductions", "amount": _money_decimal(above_line_deductions)},
            {"label": "adjusted_gross_income", "amount": _money_decimal(adjusted_gross_income)},
            {"label": "deduction_used", "amount": _money_decimal(deduction_used)},
            {"label": "taxable_before_qbi", "amount": _money_decimal(taxable_before_qbi)},
            {"label": "qbi_deduction", "amount": _money_decimal(qbi_deduction_amount)},
            {"label": "taxable_income", "amount": _money_decimal(taxable_income)},
            {"label": "federal_income_tax", "amount": _money_decimal(federal_income_tax_amount)},
            {"label": "state_income_tax", "amount": _money_decimal(state_tax)},
            {"label": "total_tax", "amount": _money_decimal(total_tax)},
        ],
        rule_version=rule_version,
        citations=_merge_citations(base_citations, state_citations),
        assumptions=assumptions,
    )


SUPPORTED_CRYPTO_METHODS = {"FIFO", "LIFO", "HIFO"}


def _capital_gains_rule_version(capital_gains_rules: dict[str, Any], federal_rules: dict[str, Any]) -> str:
    return f"{capital_gains_rules['rule_version']}+{federal_rules['rule_version']}"


def _validate_crypto_item(item: dict[str, Any], *, item_type: str, index: int) -> dict[str, Any]:
    asset = item.get("asset")
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError(f"{item_type}[{index}] asset must be non-empty")

    parsed_date = _parse_iso_date(item.get("date"), f"{item_type}[{index}].date")
    quantity = _decimal_input(item.get("quantity"), f"{item_type}[{index}].quantity")
    if quantity <= 0:
        raise ValueError(f"{item_type}[{index}] quantity must be greater than zero")

    amount_field = "cost_basis" if item_type == "lots" else "proceeds"
    amount = _decimal_input(item.get(amount_field), f"{item_type}[{index}].{amount_field}")
    if amount < 0:
        raise ValueError(f"{item_type}[{index}] {amount_field} must be zero or greater")

    return {
        "asset": asset.strip(),
        "date": parsed_date,
        "quantity": quantity,
        amount_field: amount,
    }


def _validate_crypto_inputs(
    lots: list[dict[str, Any]],
    disposals: list[dict[str, Any]],
    method: str,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_method = method.upper()
    if normalized_method not in SUPPORTED_CRYPTO_METHODS:
        raise ValueError(f"method must be one of {sorted(SUPPORTED_CRYPTO_METHODS)}")

    if not isinstance(lots, list):
        raise ValueError("lots must be a list")
    if not isinstance(disposals, list):
        raise ValueError("disposals must be a list")

    parsed_lots = [_validate_crypto_item(item, item_type="lots", index=index) for index, item in enumerate(lots)]
    parsed_disposals = [
        _validate_crypto_item(item, item_type="disposals", index=index) for index, item in enumerate(disposals)
    ]

    bought_by_asset: dict[str, Decimal] = {}
    sold_by_asset: dict[str, Decimal] = {}
    for lot in parsed_lots:
        bought_by_asset[lot["asset"]] = bought_by_asset.get(lot["asset"], Decimal("0")) + lot["quantity"]
    for disposal in parsed_disposals:
        sold_by_asset[disposal["asset"]] = sold_by_asset.get(disposal["asset"], Decimal("0")) + disposal["quantity"]

    for asset, sold_quantity in sold_by_asset.items():
        bought_quantity = bought_by_asset.get(asset, Decimal("0"))
        if sold_quantity > bought_quantity:
            shortage = sold_quantity - bought_quantity
            raise ValueError(f"Disposal quantity for {asset} exceeds available lots by {shortage}")

    return normalized_method, parsed_lots, parsed_disposals


def _sort_crypto_lots(lots: list[dict[str, Any]], method: str) -> list[dict[str, Any]]:
    if method == "FIFO":
        return sorted(lots, key=lambda item: item["date"])
    if method == "LIFO":
        return sorted(lots, key=lambda item: item["date"], reverse=True)
    return sorted(lots, key=lambda item: item["unit_cost"], reverse=True)


def _match_crypto_lots(
    lots: list[dict[str, Any]],
    disposals: list[dict[str, Any]],
    method: str,
) -> list[dict[str, Any]]:
    lots_by_asset: dict[str, list[dict[str, Any]]] = {}
    for lot in lots:
        unit_cost = lot["cost_basis"] / lot["quantity"]
        lots_by_asset.setdefault(lot["asset"], []).append(
            {
                "asset": lot["asset"],
                "date": lot["date"],
                "remaining_quantity": lot["quantity"],
                "unit_cost": unit_cost,
            }
        )

    for asset, asset_lots in lots_by_asset.items():
        lots_by_asset[asset] = _sort_crypto_lots(asset_lots, method)

    matches: list[dict[str, Any]] = []
    for disposal in sorted(disposals, key=lambda item: item["date"]):
        remaining = disposal["quantity"]
        disposal_unit_price = disposal["proceeds"] / disposal["quantity"]
        asset_lots = lots_by_asset.get(disposal["asset"], [])

        for lot in asset_lots:
            if remaining <= 0:
                break
            if lot["remaining_quantity"] <= 0:
                continue

            matched_quantity = min(remaining, lot["remaining_quantity"])
            proceeds = disposal_unit_price * matched_quantity
            cost_basis = lot["unit_cost"] * matched_quantity
            gain = proceeds - cost_basis
            term = "long" if disposal["date"] > _add_one_calendar_year(lot["date"]) else "short"
            matches.append(
                {
                    "asset": disposal["asset"],
                    "quantity": matched_quantity,
                    "acquired": lot["date"].isoformat(),
                    "sold": disposal["date"].isoformat(),
                    "proceeds": proceeds,
                    "cost_basis": cost_basis,
                    "gain": gain,
                    "term": term,
                }
            )

            lot["remaining_quantity"] -= matched_quantity
            remaining -= matched_quantity

    return matches


def _net_capital_gains(short_term_gain: Decimal, long_term_gain: Decimal) -> tuple[Decimal, Decimal]:
    if short_term_gain >= 0 and long_term_gain >= 0:
        return short_term_gain, long_term_gain
    if short_term_gain <= 0 and long_term_gain <= 0:
        return short_term_gain, long_term_gain

    total = short_term_gain + long_term_gain
    if total >= 0:
        if short_term_gain > 0:
            return total, Decimal("0")
        return Decimal("0"), total

    if short_term_gain < 0:
        return total, Decimal("0")
    return Decimal("0"), total


def _long_term_capital_gains_tax(
    *,
    ordinary_stack: Decimal,
    long_term_gain: Decimal,
    brackets: list[dict[str, Any]],
) -> Decimal:
    if long_term_gain <= 0:
        return Decimal("0")

    tax = Decimal("0")
    interval_start = ordinary_stack
    interval_end = ordinary_stack + long_term_gain
    previous_cap = Decimal("0")

    for bracket in brackets:
        cap_raw = bracket.get("up_to")
        cap = None if cap_raw is None else _decimal_rule(cap_raw)
        rate = _decimal_rule(bracket["rate"])
        bracket_start = previous_cap
        bracket_end = interval_end if cap is None else min(cap, interval_end)

        taxable_start = max(interval_start, bracket_start)
        taxable_end = min(interval_end, bracket_end)
        if taxable_end > taxable_start:
            tax += (taxable_end - taxable_start) * rate

        if cap is None or interval_end <= cap:
            break
        previous_cap = cap

    return tax


def _crypto_tax_estimate(
    *,
    net_short_term_gain: Decimal,
    net_long_term_gain: Decimal,
    filing: str,
    other_taxable_income: Decimal,
    modified_agi: Decimal | None,
    federal_rules: dict[str, Any],
    capital_gains_rules: dict[str, Any],
) -> tuple[dict[str, float], list[str]]:
    assumptions: list[str] = [
        "Crypto gain estimate uses lot matching, Schedule D netting, LTCG stacking, and NIIT rules from stored JSON.",
        "Wash sale adjustments, specific-ID documentation, cross-year carryovers, Form 8949 PDF export, "
        "and income events such as staking, airdrops, and forks are outside this function.",
    ]

    net_st, net_lt = _net_capital_gains(net_short_term_gain, net_long_term_gain)
    if net_st + net_lt < 0:
        assumptions.append(
            "Net capital loss detected; up to $3,000 may offset ordinary income and the remainder may carry forward, "
            "but this function does not calculate those items without full return context."
        )
        return (
            {
                "short_term_ordinary_tax": 0.00,
                "long_term_capital_gains_tax": 0.00,
                "net_investment_income_tax": 0.00,
                "total": 0.00,
            },
            assumptions,
        )

    taxable_st = max(Decimal("0"), net_st)
    taxable_lt = max(Decimal("0"), net_lt)
    ordinary_brackets = federal_rules["ordinary_income_brackets"][filing]
    short_term_tax = _bracket_tax_decimal(other_taxable_income + taxable_st, ordinary_brackets) - _bracket_tax_decimal(
        other_taxable_income, ordinary_brackets
    )

    ordinary_stack = other_taxable_income + taxable_st
    ltcg_tax = _long_term_capital_gains_tax(
        ordinary_stack=ordinary_stack,
        long_term_gain=taxable_lt,
        brackets=capital_gains_rules["long_term_capital_gains"]["brackets"][filing],
    )

    net_investment_income = max(Decimal("0"), taxable_st + taxable_lt)
    niit_rules = capital_gains_rules["net_investment_income_tax"]
    threshold = _decimal_rule(niit_rules["magi_thresholds"][filing])
    if modified_agi is None:
        magi = other_taxable_income + net_investment_income
        assumptions.append(
            "modified_agi was not provided; NIIT estimate approximates MAGI as other taxable income "
            "plus net investment income."
        )
    else:
        magi = modified_agi
    niit_base = min(net_investment_income, max(Decimal("0"), magi - threshold))
    niit = niit_base * _decimal_rule(niit_rules["rate"])
    total = short_term_tax + ltcg_tax + niit

    return (
        {
            "short_term_ordinary_tax": _money_decimal(short_term_tax),
            "long_term_capital_gains_tax": _money_decimal(ltcg_tax),
            "net_investment_income_tax": _money_decimal(niit),
            "total": _money_decimal(total),
        },
        assumptions,
    )


def crypto_gain_estimate(
    lots: list[dict[str, Any]],
    disposals: list[dict[str, Any]],
    method: str = "FIFO",
    filing_status: str = "single",
    other_taxable_income: float = 0.0,
    modified_agi: float | None = None,
    tax_year: int = 2025,
) -> dict[str, Any]:
    """Estimate crypto capital gains from deterministic lot matching and stored tax rules."""

    input_data = {
        "lots": lots,
        "disposals": disposals,
        "method": method,
        "filing_status": filing_status,
        "other_taxable_income": other_taxable_income,
        "modified_agi": modified_agi,
        "tax_year": tax_year,
    }
    capital_gains_rules = load_capital_gains_rules(tax_year)
    federal_rules = load_federal_rules(tax_year)
    rule_version = _capital_gains_rule_version(capital_gains_rules, federal_rules)
    citations = _citations(
        capital_gains_rules["long_term_capital_gains"],
        capital_gains_rules["short_term_capital_gains"],
        capital_gains_rules["net_investment_income_tax"],
        federal_rules["ordinary_income_brackets"],
    )

    try:
        filing = _normalize_filing_status(filing_status)
        normalized_method, parsed_lots, parsed_disposals = _validate_crypto_inputs(lots, disposals, method)
        ordinary_income = max(Decimal("0"), _decimal_input(other_taxable_income, "other_taxable_income"))
        magi = None if modified_agi is None else max(Decimal("0"), _decimal_input(modified_agi, "modified_agi"))
    except ValueError as exc:
        return _invalid_input(
            input_data=input_data,
            rule_version=rule_version,
            citations=citations,
            reason=str(exc),
        )

    matches = _match_crypto_lots(parsed_lots, parsed_disposals, normalized_method)
    short_term_gain = sum((match["gain"] for match in matches if match["term"] == "short"), Decimal("0"))
    long_term_gain = sum((match["gain"] for match in matches if match["term"] == "long"), Decimal("0"))
    net_capital_gain = short_term_gain + long_term_gain

    tax_estimate, assumptions = _crypto_tax_estimate(
        net_short_term_gain=short_term_gain,
        net_long_term_gain=long_term_gain,
        filing=filing,
        other_taxable_income=ordinary_income,
        modified_agi=magi,
        federal_rules=federal_rules,
        capital_gains_rules=capital_gains_rules,
    )

    lots_matched = [
        {
            "asset": match["asset"],
            "quantity": float(match["quantity"]),
            "acquired": match["acquired"],
            "sold": match["sold"],
            "proceeds": _money_decimal(match["proceeds"]),
            "cost_basis": _money_decimal(match["cost_basis"]),
            "gain": _money_decimal(match["gain"]),
            "term": match["term"],
        }
        for match in matches
    ]

    return _response(
        status="ok",
        input_data={**input_data, "method": normalized_method, "filing_status": filing},
        result={
            "method": normalized_method,
            "realized": {
                "short_term_gain": _money_decimal(short_term_gain),
                "long_term_gain": _money_decimal(long_term_gain),
                "net_capital_gain": _money_decimal(net_capital_gain),
            },
            "lots_matched": lots_matched,
            "tax_estimate": tax_estimate,
        },
        breakdown=[
            {"label": "short_term_gain", "amount": _money_decimal(short_term_gain)},
            {"label": "long_term_gain", "amount": _money_decimal(long_term_gain)},
            {"label": "net_capital_gain", "amount": _money_decimal(net_capital_gain)},
            {"label": "crypto_tax_estimate_total", "amount": tax_estimate["total"]},
        ],
        rule_version=rule_version,
        citations=citations,
        assumptions=assumptions,
    )


def _validate_sale_scenario(
    sale_scenario: dict[str, Any] | None,
    vest_date: date,
) -> tuple[date, Decimal] | None:
    if sale_scenario is None:
        return None
    if not isinstance(sale_scenario, dict):
        raise ValueError("sale_scenario must be an object")

    sale_date = _parse_iso_date(sale_scenario.get("sale_date"), "sale_scenario.sale_date")
    if sale_date < vest_date:
        raise ValueError("sale_date must be on or after vest_date")

    sale_price = _decimal_input(sale_scenario.get("sale_price_per_share"), "sale_scenario.sale_price_per_share")
    if sale_price < 0:
        raise ValueError("sale_price_per_share must be zero or greater")

    return sale_date, sale_price


def rsu_tax_estimate(
    shares_vested: float,
    fair_market_value_per_share: float,
    vest_date: str,
    filing_status: str = "single",
    other_taxable_income: float = 0.0,
    sale_scenario: dict[str, Any] | None = None,
    tax_year: int = 2025,
) -> dict[str, Any]:
    """Estimate RSU vesting ordinary income tax and optional sale capital gains tax."""

    input_data = {
        "shares_vested": shares_vested,
        "fair_market_value_per_share": fair_market_value_per_share,
        "vest_date": vest_date,
        "filing_status": filing_status,
        "other_taxable_income": other_taxable_income,
        "sale_scenario": sale_scenario,
        "tax_year": tax_year,
    }
    federal_rules = load_federal_rules(tax_year)
    capital_gains_rules = load_capital_gains_rules(tax_year)
    rule_version = _capital_gains_rule_version(capital_gains_rules, federal_rules)
    citations = _citations(
        federal_rules["ordinary_income_brackets"],
        capital_gains_rules["long_term_capital_gains"],
        capital_gains_rules["short_term_capital_gains"],
    )

    try:
        filing = _normalize_filing_status(filing_status)
        shares = _decimal_input(shares_vested, "shares_vested")
        if shares <= 0:
            raise ValueError("shares_vested must be greater than zero")
        fmv = _decimal_input(fair_market_value_per_share, "fair_market_value_per_share")
        if fmv < 0:
            raise ValueError("fair_market_value_per_share must be zero or greater")
        parsed_vest_date = _parse_iso_date(vest_date, "vest_date")
        ordinary_income_stack = max(Decimal("0"), _decimal_input(other_taxable_income, "other_taxable_income"))
        parsed_sale = _validate_sale_scenario(sale_scenario, parsed_vest_date)
    except ValueError as exc:
        return _invalid_input(
            input_data=input_data,
            rule_version=rule_version,
            citations=citations,
            reason=str(exc),
        )

    ordinary_income = shares * fmv
    ordinary_brackets = federal_rules["ordinary_income_brackets"][filing]
    vest_income_tax = _bracket_tax_decimal(
        ordinary_income_stack + ordinary_income,
        ordinary_brackets,
    ) - _bracket_tax_decimal(ordinary_income_stack, ordinary_brackets)

    assumptions = [
        "RSU vesting value may also be subject to FICA (Social Security and Medicare); "
        "this function does not calculate FICA, see fica_tax.",
        "Cost basis per share is the vesting fair market value under section 83 treatment.",
        "Sale price and sale date are caller-provided inputs, not forecasts.",
        "ISO, ESPP, NQSO, 83(b), AMT, withholding shortfalls, and multi-vest aggregation are outside this MVP.",
    ]

    hold_vs_sell = None
    if parsed_sale is not None:
        sale_date, sale_price = parsed_sale
        capital_gain = (sale_price - fmv) * shares
        term = "long" if sale_date > _add_one_calendar_year(parsed_vest_date) else "short"
        ordinary_stack_after_vest = ordinary_income_stack + ordinary_income
        capital_gains_tax = Decimal("0")

        if capital_gain > 0:
            if term == "long":
                capital_gains_tax = _long_term_capital_gains_tax(
                    ordinary_stack=ordinary_stack_after_vest,
                    long_term_gain=capital_gain,
                    brackets=capital_gains_rules["long_term_capital_gains"]["brackets"][filing],
                )
            else:
                capital_gains_tax = _bracket_tax_decimal(
                    ordinary_stack_after_vest + capital_gain,
                    ordinary_brackets,
                ) - _bracket_tax_decimal(ordinary_stack_after_vest, ordinary_brackets)
        elif capital_gain < 0:
            assumptions.append(
                "Sale scenario creates a capital loss; this function does not calculate the $3,000 ordinary income "
                "deduction or carryforward."
            )

        hold_vs_sell = {
            "sale_date": sale_date.isoformat(),
            "sale_price_per_share": _money_decimal(sale_price),
            "capital_gain": _money_decimal(capital_gain),
            "term": term,
            "capital_gains_tax": _money_decimal(capital_gains_tax),
            "note": "Selling at vest has near-zero capital gain; gains after holding more than one year may receive "
            "long-term capital gains treatment.",
        }

    return _response(
        status="ok",
        input_data={**input_data, "filing_status": filing},
        result={
            "vesting": {
                "shares": float(shares),
                "fmv_per_share": _money_decimal(fmv),
                "ordinary_income": _money_decimal(ordinary_income),
                "cost_basis_per_share": _money_decimal(fmv),
                "vest_income_tax": _money_decimal(vest_income_tax),
            },
            "hold_vs_sell": hold_vs_sell,
        },
        breakdown=[
            {"label": "rsu_ordinary_income", "amount": _money_decimal(ordinary_income)},
            {"label": "vest_income_tax", "amount": _money_decimal(vest_income_tax)},
            {
                "label": "capital_gains_tax",
                "amount": 0.00 if hold_vs_sell is None else hold_vs_sell["capital_gains_tax"],
            },
        ],
        rule_version=rule_version,
        citations=citations,
        assumptions=assumptions,
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
