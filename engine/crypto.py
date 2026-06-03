"""Crypto lot matching and federal/state gain estimates."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .brackets import _bracket_tax_decimal, _long_term_capital_gains_tax
from .dates import _add_one_calendar_year, _parse_iso_date
from .filing import _normalize_filing_status
from .money import _decimal_input, _decimal_rule, _money_decimal
from .responses import _citations, _invalid_input, _merge_citations, _response
from .rules_loader import load_capital_gains_rules, load_federal_rules, load_state_rules
from .state import _state_taxable_base, state_capital_gains_excise

__all__ = [
    "SUPPORTED_CRYPTO_METHODS",
    "_capital_gains_rule_version",
    "_net_capital_gains",
    "_validate_crypto_item",
    "_validate_crypto_inputs",
    "_sort_crypto_lots",
    "_match_crypto_lots",
    "_crypto_tax_estimate",
    "_crypto_state_not_covered",
    "_crypto_state_tax",
    "crypto_gain_estimate",
]

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

def _crypto_state_not_covered(
    code: str,
    reason: str,
    citations: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    return (
        {
            "state": code,
            "status": "not_covered",
            "not_covered": True,
            "type": "not_covered",
            "tax": 0.00,
            "reason": reason,
        },
        citations or [],
        ["Crypto state tax is not covered for the requested state; state tax is treated as $0."],
    )

def _crypto_state_tax(
    state_code: str,
    *,
    net_short_term_gain: Decimal,
    net_long_term_gain: Decimal,
    other_state_income: Decimal,
    filing: str,
    tax_year: int,
    state_rules: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    code = state_code.upper()
    state = state_rules["states"].get(code)
    if not state:
        return _crypto_state_not_covered(
            code,
            f"State {code} is not present in stored {tax_year} state rules.",
        )

    state_citations = _citations(state)
    status = state.get("status")
    if status != "effective":
        return _crypto_state_not_covered(
            code,
            f"State {code} rule status is {status}; crypto state tax calculation is blocked.",
            state_citations,
        )

    capital_gains_excise = state.get("capital_gains_excise")
    if capital_gains_excise:
        excise_citations = _merge_citations(state_citations, _citations(capital_gains_excise))
        excise = state_capital_gains_excise(state, net_long_term_gain=net_long_term_gain)
        if excise is None:
            return _crypto_state_not_covered(
                code,
                f"State {code} capital gains excise data is missing.",
                state_citations,
            )
        return (
            {
                "state": code,
                "status": "ok",
                "type": "excise",
                "tax": _money_decimal(excise["tax"]),
                "long_term_only": excise["long_term_only"],
                "long_term_gain": _money_decimal(excise["long_term_gain"]),
                "standard_deduction": _money_decimal(excise["standard_deduction"]),
                "taxable_washington_capital_gain": _money_decimal(excise["taxable_capital_gains"]),
                "rate": float(excise["rate"]),
                "surtax_rate": float(excise["surtax_rate"]),
                "surtax_threshold": _money_decimal(excise["surtax_threshold"]),
            },
            excise_citations,
            [
                "Washington capital gains excise is modeled only on net long-term capital gains above the stored "
                "standard deduction; short-term gains are not included.",
                "Washington residency and allocation are assumed in-state; exempt asset categories such as real "
                "estate, retirement accounts, and certain business assets are not modeled for crypto.",
                "The Washington $1,000,000 tier is applied to taxable Washington capital gains after the standard "
                "deduction, matching the archived DOR special notice wording.",
            ],
        )

    tax_type = state.get("income_tax_type")
    if tax_type == "none":
        return (
            {
                "state": code,
                "status": "ok",
                "type": "no_state_income_tax",
                "tax": 0.00,
            },
            state_citations,
            ["Requested state has no individual income tax and no modeled crypto capital gains excise."],
        )

    tax_base = state.get("tax_base", {})
    tax_base_citations = _citations(tax_base)
    if tax_type not in {"flat", "progressive"} or tax_base.get("capital_gains_treatment") != "ordinary_income":
        return _crypto_state_not_covered(
            code,
            f"State {code} does not have modeled ordinary-income capital gains treatment.",
            _merge_citations(state_citations, tax_base_citations),
        )

    # Schedule D netting: states tax the NET capital gain that flows into federal AGI, so a
    # short-term loss offsets a long-term gain (and vice versa) before the state rate applies.
    # Must net the same way the federal _crypto_tax_estimate does, or a net loss would be taxed.
    gain = max(Decimal("0"), net_short_term_gain + net_long_term_gain)
    try:
        base_without_gain = _state_taxable_base(
            state,
            federal_agi=other_state_income,
            federal_taxable_income=other_state_income,
            federal_qbi_deduction=Decimal("0"),
            filing=filing,
        )
        base_with_gain = _state_taxable_base(
            state,
            federal_agi=other_state_income + gain,
            federal_taxable_income=other_state_income + gain,
            federal_qbi_deduction=Decimal("0"),
            filing=filing,
        )
    except ValueError as exc:
        return _crypto_state_not_covered(
            code,
            str(exc),
            _merge_citations(state_citations, tax_base_citations),
        )

    # Incremental state tax in full precision, rounded ONCE (avoids the off-by-a-cent drift that
    # double-rounding tax_with_gain - tax_without_gain can introduce). Flat states are linear;
    # progressive states use the Decimal bracket helper. Status/coverage were already validated
    # above, so a missing bracket/rate here is treated defensively as not_covered.
    try:
        if state.get("income_tax_type") == "flat":
            incremental = (base_with_gain - base_without_gain) * _decimal_rule(state["flat_rate"])
        else:
            brackets = state["brackets"][filing]
            incremental = _bracket_tax_decimal(base_with_gain, brackets) - _bracket_tax_decimal(
                base_without_gain, brackets
            )
    except (KeyError, ValueError) as exc:
        return _crypto_state_not_covered(
            code,
            str(exc),
            _merge_citations(state_citations, tax_base_citations),
        )

    state_tax = _money_decimal(max(Decimal("0"), incremental))
    return (
        {
            "state": code,
            "status": "ok",
            "type": "ordinary_income",
            "tax": state_tax,
            "capital_gains_treatment": "ordinary_income",
            "taxable_base_without_gain": _money_decimal(base_without_gain),
            "taxable_base_with_gain": _money_decimal(base_with_gain),
        },
        _merge_citations(state_citations, tax_base_citations),
        [
            "Covered income-tax states model crypto net capital gains as ordinary income at the state level; "
            "short-term and long-term gains are not treated differently for these states.",
            "Crypto state tax uses other_taxable_income as the state stacking base, matching the income_summary "
            "MVP approximation; state-specific residual adjustments and credits are not modeled.",
            "Net capital losses produce $0 crypto state tax in this function.",
        ],
    )

def crypto_gain_estimate(
    lots: list[dict[str, Any]],
    disposals: list[dict[str, Any]],
    method: str = "FIFO",
    filing_status: str = "single",
    other_taxable_income: float = 0.0,
    modified_agi: float | None = None,
    state_code: str | None = None,
    tax_year: int = 2026,
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
    if state_code is not None:
        input_data["state_code"] = state_code.upper()
    capital_gains_rules = load_capital_gains_rules(tax_year)
    federal_rules = load_federal_rules(tax_year)
    state_rules = load_state_rules(tax_year) if state_code is not None else None
    rule_version = _capital_gains_rule_version(capital_gains_rules, federal_rules)
    if state_rules is not None:
        rule_version = f"{rule_version}+{state_rules['rule_version']}"
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
    result_citations = citations
    state_result: dict[str, Any] | None = None
    if state_code is not None and state_rules is not None:
        state_result, state_citations, state_assumptions = _crypto_state_tax(
            state_code,
            net_short_term_gain=short_term_gain,
            net_long_term_gain=long_term_gain,
            other_state_income=ordinary_income,
            filing=filing,
            tax_year=tax_year,
            state_rules=state_rules,
        )
        result_citations = _merge_citations(result_citations, state_citations)
        assumptions.extend(state_assumptions)

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

    result = {
        "method": normalized_method,
        "realized": {
            "short_term_gain": _money_decimal(short_term_gain),
            "long_term_gain": _money_decimal(long_term_gain),
            "net_capital_gain": _money_decimal(net_capital_gain),
        },
        "lots_matched": lots_matched,
        "tax_estimate": tax_estimate,
    }
    if state_result is not None:
        result["state"] = state_result
        result["total_tax_including_state"] = _money_decimal(
            _decimal_rule(tax_estimate["total"]) + _decimal_rule(state_result["tax"])
        )

    breakdown = [
        {"label": "short_term_gain", "amount": _money_decimal(short_term_gain)},
        {"label": "long_term_gain", "amount": _money_decimal(long_term_gain)},
        {"label": "net_capital_gain", "amount": _money_decimal(net_capital_gain)},
        {"label": "crypto_tax_estimate_total", "amount": tax_estimate["total"]},
    ]
    if state_result is not None:
        breakdown.append({"label": "crypto_state_tax", "amount": state_result["tax"]})
        breakdown.append({"label": "total_tax_including_state", "amount": result["total_tax_including_state"]})

    return _response(
        status="ok",
        input_data={**input_data, "method": normalized_method, "filing_status": filing},
        result=result,
        breakdown=breakdown,
        rule_version=rule_version,
        citations=result_citations,
        assumptions=assumptions,
    )
