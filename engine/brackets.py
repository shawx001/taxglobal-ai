"""Bracket and capital-gain tax helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .money import _decimal_rule, _money

__all__ = ["bracket_tax", "_bracket_tax_decimal", "_long_term_capital_gains_tax"]

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
