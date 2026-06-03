"""Combined income tax summary orchestration."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .brackets import _bracket_tax_decimal, _long_term_capital_gains_tax
from .feie import feie_estimate
from .filing import _normalize_filing_status
from .money import _decimal_input, _decimal_rule, _money_decimal, _money_quantized
from .payroll import _combined_payroll
from .qbi import qbi_deduction
from .responses import _citations, _invalid_input, _merge_citations, _response
from .rules_loader import (
    load_capital_gains_rules,
    load_federal_rules,
    load_fica_rules,
    load_qbi_rules,
    load_state_rules,
)
from .state import _state_taxable_base, state_income_tax

__all__ = ["_summary_rule_version", "income_tax_summary"]

def _summary_rule_version(
    tax_year: int,
    federal_rules: dict[str, Any],
    fica_rules: dict[str, Any],
    qbi_rules: dict[str, Any],
    capital_gains_rules: dict[str, Any],
    state_rules: dict[str, Any],
) -> str:
    return (
        f"us-{tax_year}-income-summary-v0.2+"
        f"{federal_rules['rule_version']}+{fica_rules['rule_version']}+"
        f"{qbi_rules['rule_version']}+{capital_gains_rules['rule_version']}+{state_rules['rule_version']}"
    )

def income_tax_summary(
    net_self_employment_profit: float = 0.0,
    *,
    w2_wages: float = 0.0,
    other_ordinary_income: float = 0.0,
    long_term_capital_gain: float = 0.0,
    short_term_capital_gain: float = 0.0,
    modified_agi: float | None = None,
    foreign_earned_income: float = 0.0,
    days_abroad: int = 0,
    filing_status: str = "single",
    state_code: str | None = None,
    se_health_insurance: float = 0.0,
    retirement_contributions: float = 0.0,
    qbi_w2_wages: float = 0.0,
    qbi_ubia: float = 0.0,
    is_sstb: bool = False,
    deduction: float | None = None,
    tax_year: int = 2026,
) -> dict[str, Any]:
    """Combine W-2, self-employment, capital gains, QBI, federal, payroll, NIIT, and state tax into one summary."""

    raw_input = {
        "w2_wages": w2_wages,
        "net_self_employment_profit": net_self_employment_profit,
        "other_ordinary_income": other_ordinary_income,
        "long_term_capital_gain": long_term_capital_gain,
        "short_term_capital_gain": short_term_capital_gain,
        "modified_agi": modified_agi,
        "foreign_earned_income": foreign_earned_income,
        "days_abroad": days_abroad,
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
    capital_gains_rules = load_capital_gains_rules(tax_year)
    state_rules = load_state_rules(tax_year)
    rule_version = _summary_rule_version(
        tax_year,
        federal_rules,
        fica_rules,
        qbi_rules,
        capital_gains_rules,
        state_rules,
    )

    base_citations = _merge_citations(
        _citations(federal_rules["standard_deduction"], federal_rules["ordinary_income_brackets"]),
        _citations(
            fica_rules["social_security"],
            fica_rules["medicare"],
            fica_rules["additional_medicare"],
            fica_rules["self_employment"],
        ),
        _citations(qbi_rules["qbi_deduction"], qbi_rules["qbi_deduction"].get("wage_ubia_limit", {})),
        _citations(
            capital_gains_rules["long_term_capital_gains"],
            capital_gains_rules["short_term_capital_gains"],
            capital_gains_rules["net_investment_income_tax"],
        ),
    )

    try:
        filing = _normalize_filing_status(filing_status)
        w2 = max(Decimal("0"), _decimal_input(w2_wages, "w2_wages"))
        net_profit = max(Decimal("0"), _decimal_input(net_self_employment_profit, "net_self_employment_profit"))
        other_income = max(Decimal("0"), _decimal_input(other_ordinary_income, "other_ordinary_income"))
        long_term_gain = max(Decimal("0"), _decimal_input(long_term_capital_gain, "long_term_capital_gain"))
        short_term_gain = max(Decimal("0"), _decimal_input(short_term_capital_gain, "short_term_capital_gain"))
        modified_agi_value = (
            None if modified_agi is None else max(Decimal("0"), _decimal_input(modified_agi, "modified_agi"))
        )
        foreign_income = max(Decimal("0"), _decimal_input(foreign_earned_income, "foreign_earned_income"))
        days_abroad_decimal = _decimal_input(days_abroad, "days_abroad")
        if days_abroad_decimal != days_abroad_decimal.to_integral_value():
            raise ValueError("days_abroad must be a whole number of days")
        days_abroad_value = int(days_abroad_decimal)
        if days_abroad_value < 0 or days_abroad_value > 366:
            raise ValueError("days_abroad must be between 0 and 366")
        health_insurance = max(Decimal("0"), _decimal_input(se_health_insurance, "se_health_insurance"))
        retirement = max(Decimal("0"), _decimal_input(retirement_contributions, "retirement_contributions"))
        qbi_w2 = max(Decimal("0"), _decimal_input(qbi_w2_wages, "qbi_w2_wages"))
        ubia = max(Decimal("0"), _decimal_input(qbi_ubia, "qbi_ubia"))
        deduction_used = (
            _decimal_rule(federal_rules["standard_deduction"][filing])
            if deduction is None
            else max(Decimal("0"), _decimal_input(deduction, "deduction"))
        )
    except (TypeError, ValueError) as exc:
        return _invalid_input(
            input_data=raw_input,
            rule_version=rule_version,
            reason=str(exc),
            citations=base_citations,
        )

    payroll = _combined_payroll(w2, net_profit, filing, fica_rules)
    se_tax = payroll["self_employment_tax"]
    additional_medicare_tax = payroll["additional_medicare_tax"]
    deductible_half_se_tax = payroll["deductible_half_se_tax"]
    w2_fica_tax = payroll["w2_fica_tax"]
    total_payroll_tax = payroll["total_payroll_tax"]

    feie_result: dict[str, Any] | None = None
    feie_citations: list[dict[str, Any]] = []
    feie_assumptions: list[str] = []
    feie_excluded_income = Decimal("0")
    if foreign_income > 0:
        feie_result = feie_estimate(_money_decimal(foreign_income), days_abroad_value, tax_year)
        feie_citations = feie_result["citations"]
        feie_assumptions = feie_result["assumptions"]
        feie_excluded_income = _decimal_rule(feie_result["result"]["excluded_income"])
    taxable_foreign_income = max(Decimal("0"), foreign_income - feie_excluded_income)
    foreign_tax_rate_stacking_applied = feie_excluded_income > 0
    summary_citations = _merge_citations(base_citations, feie_citations)

    above_line_deductions = deductible_half_se_tax + health_insurance + retirement
    adjusted_gross_income = max(
        Decimal("0"),
        w2
        + net_profit
        + other_income
        + short_term_gain
        + long_term_gain
        + taxable_foreign_income
        - above_line_deductions,
    )
    taxable_before_qbi = max(Decimal("0"), adjusted_gross_income - deduction_used)
    qbi_amount = max(Decimal("0"), net_profit - above_line_deductions)

    qbi_result = qbi_deduction(
        qbi=qbi_amount,
        taxable_income=taxable_before_qbi,
        filing_status=filing,
        net_capital_gain=long_term_gain,
        w2_wages=qbi_w2,
        ubia=ubia,
        is_sstb=is_sstb,
        tax_year=tax_year,
    )
    if qbi_result["status"] != "ok":
        return _invalid_input(
            input_data={**raw_input, "filing_status": filing},
            rule_version=rule_version,
            reason=f"QBI deduction failed: {qbi_result['reason']}",
            citations=_merge_citations(summary_citations, qbi_result["citations"]),
            assumptions=qbi_result["assumptions"],
        )
    qbi_deduction_amount = _decimal_rule(qbi_result["result"]["deduction"])

    taxable_income = max(Decimal("0"), taxable_before_qbi - qbi_deduction_amount)
    long_term_gain_taxed = max(Decimal("0"), min(long_term_gain, taxable_income))
    ordinary_taxable_income = max(Decimal("0"), taxable_income - long_term_gain_taxed)
    ordinary_brackets = federal_rules["ordinary_income_brackets"][filing]
    federal_income_tax_amount = max(
        Decimal("0"),
        _bracket_tax_decimal(ordinary_taxable_income + feie_excluded_income, ordinary_brackets)
        - _bracket_tax_decimal(feie_excluded_income, ordinary_brackets),
    )
    long_term_capital_gains_tax = _long_term_capital_gains_tax(
        ordinary_stack=ordinary_taxable_income,
        long_term_gain=long_term_gain_taxed,
        brackets=capital_gains_rules["long_term_capital_gains"]["brackets"][filing],
    )
    net_investment_income = max(Decimal("0"), short_term_gain + long_term_gain)
    niit_rules = capital_gains_rules["net_investment_income_tax"]
    niit_threshold = _decimal_rule(niit_rules["magi_thresholds"][filing])
    magi_for_niit = (
        adjusted_gross_income + feie_excluded_income if modified_agi_value is None else modified_agi_value
    )
    niit_base = min(net_investment_income, max(Decimal("0"), magi_for_niit - niit_threshold))
    net_investment_income_tax = niit_base * _decimal_rule(niit_rules["rate"])

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
                    citations=summary_citations,
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

    total_tax = (
        _money_quantized(federal_income_tax_amount)
        + _money_quantized(long_term_capital_gains_tax)
        + _money_quantized(total_payroll_tax)
        + _money_quantized(net_investment_income_tax)
        + _money_quantized(state_tax)
    )
    quarterly_estimate = total_tax / Decimal("4")

    assumptions = [
        "Income summary combines W-2 wages, self-employment income, QBI, federal ordinary income, payroll tax, "
        "capital gains, NIIT, and state income tax rules.",
        "W-2 wages are assumed to include W-2-reported RSU vesting and other wage income already subject to "
        "employee-side FICA.",
        "other_ordinary_income is treated as ordinary taxable income for income-tax stacking, but not as W-2 wages "
        "or self-employment earnings for payroll tax.",
        "Short-term capital gains are taxed as ordinary income, but are not treated as W-2 wages, "
        "self-employment earnings, or QBI.",
        "Long-term capital gains use stored QDCGT-style stacking brackets; taxable_income is total taxable income, "
        "while ordinary_taxable_income is the ordinary-rate portion before long-term capital gains tax.",
        "Net capital losses, the $3,000 capital loss deduction, and capital loss carryovers are not modeled in this "
        "combined summary.",
        "Washington long-term capital gains excise is not included in income_tax_summary; use the crypto module's "
        "state_code='WA' path for that standalone excise estimate.",
        "State taxable bases use stored tax_base data for start point, state standard deduction or exemption "
        "allowance, and QBI conformity where available.",
        "State-specific residual adjustments are not modeled, including NY tax benefit recapture above $107,650 "
        "NYAGI, IL/GA retirement subtractions, CA Schedule CA adjustments, age/blind additional amounts, "
        "state credits, and dependent-specific IL exemption counts.",
        "NIIT is not applied to active self-employment income in this summary.",
        "Self-employment health insurance and retirement contributions are caller-provided above-line deductions.",
        "w2_wages is used as both the income-tax wage base and the FICA (Social Security/Medicare) wage base; "
        "the MVP assumes W-2 Box 1 equals Box 5 (no pre-tax deductions splitting them), with Social Security "
        "capped at the wage base.",
        "AMT, equity-option timing, passive foreign income, foreign tax credits, and credits are not modeled in this "
        "combined income block.",
    ]
    if modified_agi_value is None and net_investment_income > 0:
        assumptions.append(
            "modified_agi was not provided; NIIT uses adjusted_gross_income plus any FEIE excluded income as the MVP "
            "MAGI approximation. Pass modified_agi when return-level MAGI differs."
        )
    if foreign_income > 0:
        assumptions.extend(feie_assumptions)
        assumptions.extend(
            [
                "FEIE rate stacking is applied by placing excluded foreign earned income below the non-excluded "
                "ordinary taxable income in the federal brackets.",
                "Most states do not conform to the federal FEIE; this MVP uses the stored state AGI tax_base path "
                "and does not model state-specific foreign earned income adjustments.",
                "When FEIE and large long-term capital gains coexist, the IRS combined Foreign Earned Income and "
                "QDCGT worksheets may differ from this MVP stacking simplification.",
                "Foreign earned income is assumed not to be subject to US FICA or self-employment tax in this "
                "summary; foreign self-employment and totalization agreements are not modeled.",
                "Foreign housing exclusion, bona fide residence testing, FTC, and passive foreign income are not "
                "modeled in this combined FEIE block.",
            ]
        )
    if state_result is not None and state_result["status"] != "ok":
        assumptions.append(
            "State income tax is not covered for the requested state; total tax includes federal income tax and "
            "total payroll tax (W-2 FICA + self-employment tax + Additional Medicare) only, with no state tax."
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
        "w2_wages": _money_decimal(w2),
        "foreign_earned_income": _money_decimal(foreign_income),
        "feie_excluded_income": _money_decimal(feie_excluded_income),
        "foreign_tax_rate_stacking_applied": foreign_tax_rate_stacking_applied,
        "short_term_capital_gain": _money_decimal(short_term_gain),
        "long_term_capital_gain": _money_decimal(long_term_gain),
        "w2_fica_tax": _money_decimal(w2_fica_tax),
        "self_employment_tax": _money_decimal(se_tax),
        "additional_medicare_tax": _money_decimal(additional_medicare_tax),
        "deductible_half_se_tax": _money_decimal(deductible_half_se_tax),
        "total_payroll_tax": _money_decimal(total_payroll_tax),
        "adjusted_gross_income": _money_decimal(adjusted_gross_income),
        "deduction_used": _money_decimal(deduction_used),
        "taxable_before_qbi": _money_decimal(taxable_before_qbi),
        "qbi_deduction": _money_decimal(qbi_deduction_amount),
        "taxable_income": _money_decimal(taxable_income),
        "ordinary_taxable_income": _money_decimal(ordinary_taxable_income),
        "state_taxable_base": None if normalized_state_code is None else _money_decimal(state_taxable_base),
        "state_income_tax": state_income_tax_result,
        "federal_income_tax": _money_decimal(federal_income_tax_amount),
        "long_term_capital_gains_tax": _money_decimal(long_term_capital_gains_tax),
        "net_investment_income_tax": _money_decimal(net_investment_income_tax),
        "total_tax": _money_decimal(total_tax),
        "quarterly_estimate": _money_decimal(quarterly_estimate),
    }

    return _response(
        status="ok",
        input_data={
            **raw_input,
            "filing_status": filing,
            "w2_wages": _money_decimal(w2),
            "net_self_employment_profit": _money_decimal(net_profit),
            "other_ordinary_income": _money_decimal(other_income),
            "foreign_earned_income": _money_decimal(foreign_income),
            "days_abroad": days_abroad_value,
            "short_term_capital_gain": _money_decimal(short_term_gain),
            "long_term_capital_gain": _money_decimal(long_term_gain),
            "modified_agi": None if modified_agi_value is None else _money_decimal(modified_agi_value),
            "se_health_insurance": _money_decimal(health_insurance),
            "retirement_contributions": _money_decimal(retirement),
            "qbi_w2_wages": _money_decimal(qbi_w2),
            "qbi_ubia": _money_decimal(ubia),
            "deduction": _money_decimal(deduction_used),
        },
        result=result,
        breakdown=[
            {"label": "w2_wages", "amount": _money_decimal(w2)},
            {"label": "w2_fica_tax", "amount": _money_decimal(w2_fica_tax)},
            {"label": "net_self_employment_profit", "amount": _money_decimal(net_profit)},
            {"label": "foreign_earned_income", "amount": _money_decimal(foreign_income)},
            {"label": "feie_excluded_income", "amount": _money_decimal(feie_excluded_income)},
            {"label": "short_term_capital_gain", "amount": _money_decimal(short_term_gain)},
            {"label": "long_term_capital_gain", "amount": _money_decimal(long_term_gain)},
            {"label": "deductible_half_se_tax", "amount": _money_decimal(deductible_half_se_tax)},
            {"label": "above_line_deductions", "amount": _money_decimal(above_line_deductions)},
            {"label": "adjusted_gross_income", "amount": _money_decimal(adjusted_gross_income)},
            {"label": "deduction_used", "amount": _money_decimal(deduction_used)},
            {"label": "taxable_before_qbi", "amount": _money_decimal(taxable_before_qbi)},
            {"label": "qbi_deduction", "amount": _money_decimal(qbi_deduction_amount)},
            {"label": "taxable_income", "amount": _money_decimal(taxable_income)},
            {"label": "ordinary_taxable_income", "amount": _money_decimal(ordinary_taxable_income)},
            {"label": "federal_income_tax", "amount": _money_decimal(federal_income_tax_amount)},
            {"label": "long_term_capital_gains_tax", "amount": _money_decimal(long_term_capital_gains_tax)},
            {"label": "net_investment_income_tax", "amount": _money_decimal(net_investment_income_tax)},
            {"label": "state_income_tax", "amount": _money_decimal(state_tax)},
            {"label": "total_payroll_tax", "amount": _money_decimal(total_payroll_tax)},
            {"label": "total_tax", "amount": _money_decimal(total_tax)},
        ],
        rule_version=rule_version,
        citations=_merge_citations(summary_citations, state_citations),
        assumptions=assumptions,
    )
