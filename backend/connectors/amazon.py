"""Amazon SP-API connector (marketplace facilitator -> Amazon collects/remits)."""

from __future__ import annotations

from .base import EcommerceConnector, StateSales


class AmazonConnector(EcommerceConnector):
    platform = "amazon"
    # Amazon IS a marketplace facilitator: it collects and remits sales tax on
    # the seller's behalf in facilitator states, but the seller may still owe
    # income-tax filings and should understand where nexus is created.
    is_marketplace_facilitator = True
    authorize_endpoint = "https://sellercentral.amazon.com/apps/authorize/consent"
    token_endpoint = "https://api.amazon.com/auth/o2/token"
    default_scopes = ("sellingpartnerapi::reports",)

    def _sandbox_sales(self) -> tuple[StateSales, ...]:
        return (
            StateSales(state="CA", sales_amount=600_000.0, transaction_count=5_000),
            StateSales(state="TX", sales_amount=300_000.0, transaction_count=2_500),
            StateSales(state="FL", sales_amount=200_000.0, transaction_count=1_800),
        )
