"""RSU vesting and sale tax estimates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from .brackets import _bracket_tax_decimal, _long_term_capital_gains_tax
from .crypto import _capital_gains_rule_version
from .dates import _add_one_calendar_year, _parse_iso_date
from .filing import _normalize_filing_status
from .money import _decimal_input, _money_decimal
from .responses import _citations, _invalid_input, _response
from .rules_loader import load_capital_gains_rules, load_federal_rules

__all__ = ["_validate_sale_scenario", "rsu_tax_estimate"]

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
    tax_year: int = 2026,
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
