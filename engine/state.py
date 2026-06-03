"""State income tax calculations and tax-base helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .brackets import bracket_tax
from .filing import _normalize_filing_status
from .money import _decimal_rule, _money
from .responses import _citations, _not_covered, _response
from .rules_loader import load_state_rules

__all__ = ["state_income_tax", "_state_taxable_base"]

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
    return max(Decimal("0"), federal_agi - standard_deduction)
