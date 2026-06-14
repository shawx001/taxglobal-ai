"""Bridge a normalized ``ConnectorResult`` to the ``nexus_estimate`` engine.

For each state with sales, runs the stored economic-nexus rule. Marketplace-
facilitator platforms (Amazon/eBay/Etsy) collect & remit sales tax for the
seller, so the result flags that facilitator-collected sales may not create a
seller filing duty — but nexus is still reported honestly for visibility.
"""

from __future__ import annotations

from typing import Any

from engine import nexus_estimate

from .base import ConnectorResult


def evaluate_connector_nexus(result: ConnectorResult, *, tax_year: int = 2026) -> dict[str, Any]:
    """Run ``nexus_estimate`` for every state in the connector result."""

    states: list[dict[str, Any]] = []
    for state_sales in result.sales_by_state:
        estimate = nexus_estimate(
            state_sales.state,
            state_sales.sales_amount,
            state_sales.transaction_count,
            tax_year=tax_year,
        )
        states.append(
            {
                "state": state_sales.state,
                "sales_amount": state_sales.sales_amount,
                "transaction_count": state_sales.transaction_count,
                "nexus": estimate,
            }
        )

    facilitator_note = (
        "Amazon-style marketplace facilitators collect and remit sales tax on facilitated sales; "
        "economic nexus is still reported for visibility and for non-facilitated or income-tax obligations."
        if result.is_marketplace_facilitator
        else "Independent store: the seller is responsible for collecting and remitting sales tax where nexus exists."
    )

    return {
        "platform": result.platform,
        "is_marketplace_facilitator": result.is_marketplace_facilitator,
        "sandbox": result.sandbox,
        "tax_year": tax_year,
        "total_sales": result.total_sales,
        "facilitator_note": facilitator_note,
        "states": states,
    }
