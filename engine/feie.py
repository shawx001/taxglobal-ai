"""Foreign earned income exclusion estimate."""

from __future__ import annotations

from typing import Any

from .money import _money
from .responses import _citations, _response
from .rules_loader import load_feie_rules

__all__ = ["feie_estimate"]

def feie_estimate(foreign_earned_income: float, days_abroad: int, tax_year: int = 2026) -> dict[str, Any]:
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
