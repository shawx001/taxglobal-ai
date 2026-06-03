"""Federal ordinary income tax calculation."""

from __future__ import annotations

from typing import Any

from .brackets import bracket_tax
from .filing import _normalize_filing_status
from .money import _money
from .responses import _citations, _response
from .rules_loader import load_federal_rules

__all__ = ["federal_income_tax"]

def federal_income_tax(
    gross_income: float,
    filing_status: str = "single",
    deduction: float | None = None,
    tax_year: int = 2026,
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
