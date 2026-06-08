"""State income tax calculations and tax-base helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .brackets import bracket_tax
from .filing import _normalize_filing_status
from .money import _decimal_rule, _money
from .responses import _citations, _not_covered, _response
from .rules_loader import load_state_rules

__all__ = ["state_income_tax", "state_capital_gains_excise", "_state_taxable_base"]

def state_income_tax(
    state_code: str,
    taxable_income: float,
    filing_status: str = "single",
    tax_year: int = 2026,
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
            reason=f"State {code} is not present in stored tax-year {tax_year} state rules.",
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

def state_capital_gains_excise(
    state_block: dict[str, Any],
    *,
    net_long_term_gain: Decimal,
) -> dict[str, Any] | None:
    capital_gains_excise = state_block.get("capital_gains_excise")
    if not capital_gains_excise:
        return None

    long_term_gain = max(Decimal("0"), net_long_term_gain)
    standard_deduction = _decimal_rule(capital_gains_excise["standard_deduction"])
    taxable_capital_gains = max(Decimal("0"), long_term_gain - standard_deduction)
    threshold = _decimal_rule(capital_gains_excise["surtax_threshold"])
    base_rate = _decimal_rule(capital_gains_excise["rate"])
    surtax_rate = _decimal_rule(capital_gains_excise["surtax_rate"])
    base_tax = min(taxable_capital_gains, threshold) * base_rate
    surtax = max(Decimal("0"), taxable_capital_gains - threshold) * (base_rate + surtax_rate)
    tax = base_tax + surtax
    return {
        "tax": tax,
        "long_term_only": bool(capital_gains_excise.get("long_term_only")),
        "long_term_gain": long_term_gain,
        "standard_deduction": standard_deduction,
        "taxable_capital_gains": taxable_capital_gains,
        "rate": base_rate,
        "surtax_rate": surtax_rate,
        "surtax_threshold": threshold,
    }

def _state_taxable_base(
    state_block: dict[str, Any],
    *,
    gross_income: Decimal,
    federal_agi: Decimal,
    federal_taxable_income: Decimal,
    federal_qbi_deduction: Decimal,
    filing: str,
    federal_income_tax: Decimal = Decimal("0"),
) -> Decimal:
    """Calculate state taxable base from stored state tax_base data."""

    tax_base = state_block.get("tax_base")
    if tax_base is None:
        return federal_taxable_income

    start_from = tax_base["start_from"]
    if start_from == "gross_income":
        if tax_base.get("no_tax_gross_income_threshold"):
            no_tax_threshold = _decimal_rule(tax_base["no_tax_gross_income_threshold"][filing])
            if gross_income <= no_tax_threshold:
                return Decimal("0")
        base = gross_income
        if tax_base.get("exemption_per_person"):
            exemption_count = (
                Decimal("2")
                if filing in {"married_filing_jointly", "qualifying_surviving_spouse"}
                else Decimal("1")
            )
            base -= _decimal_rule(tax_base["exemption_per_person"]) * exemption_count
        elif tax_base.get("standard_deduction"):
            base -= _decimal_rule(tax_base["standard_deduction"][filing])
        return max(Decimal("0"), base)

    if start_from == "federal_taxable_income":
        addback = federal_qbi_deduction if tax_base.get("qbi_addback") else Decimal("0")
        return max(Decimal("0"), federal_taxable_income + addback)

    if start_from != "federal_agi":
        raise ValueError(f"Unsupported state tax_base start_from: {start_from}")
    if tax_base.get("allows_qbi"):
        raise ValueError("federal_agi tax_base with allows_qbi=true is not modeled")

    if tax_base.get("uses_exemption_allowance"):
        exemption_count = Decimal("2") if filing == "married_filing_jointly" else Decimal("1")
        phaseout = _decimal_rule(tax_base["exemption_phaseout_agi"][filing])
        allowance = Decimal("0")
        if federal_agi <= phaseout:
            allowance = _decimal_rule(tax_base["exemption_allowance_per_person"]) * exemption_count
        return max(Decimal("0"), federal_agi - allowance)

    standard_deduction = _decimal_rule(tax_base["standard_deduction"][filing])
    base = federal_agi - standard_deduction
    federal_tax_subtraction = tax_base.get("federal_tax_subtraction")
    if federal_tax_subtraction:
        steps = federal_tax_subtraction["phaseout_table"][filing]
        limit: Decimal | None = None
        for step in steps:
            # Some official tables use half-open ranges; data can encode those with cent-level upper caps.
            agi_up_to = step["agi_up_to"]
            if agi_up_to is None or federal_agi <= _decimal_rule(agi_up_to):
                limit = _decimal_rule(step["limit"])
                break
        if limit is None:
            raise ValueError("federal_tax_subtraction.phaseout_table must end with a catch-all step")
        base -= min(federal_income_tax, limit)
    return max(Decimal("0"), base)
