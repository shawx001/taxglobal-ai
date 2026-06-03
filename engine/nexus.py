"""Sales-tax nexus estimate."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .money import _decimal_rule, _money_decimal
from .responses import _citations, _not_covered, _response
from .rules_loader import load_nexus_rules

__all__ = ["NEXUS_APPROACHING_RATIO", "_compare_threshold", "nexus_estimate"]

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
    tax_year: int = 2026,
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
            reason=f"State {code} is not present in stored tax-year {tax_year} nexus rules.",
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
