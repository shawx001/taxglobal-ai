"""Shopify connector (independent store -> the seller self-files sales tax)."""

from __future__ import annotations

from .base import EcommerceConnector, StateSales


class ShopifyConnector(EcommerceConnector):
    platform = "shopify"
    # Shopify is NOT a marketplace facilitator: the seller collects and remits.
    is_marketplace_facilitator = False
    authorize_endpoint = "https://{shop}.myshopify.com/admin/oauth/authorize"
    token_endpoint = "https://{shop}.myshopify.com/admin/oauth/access_token"
    default_scopes = ("read_orders", "read_products")

    def _sandbox_sales(self) -> tuple[StateSales, ...]:
        return (
            StateSales(state="CA", sales_amount=250_000.0, transaction_count=1_200),
            StateSales(state="NY", sales_amount=120_000.0, transaction_count=600),
            StateSales(state="TX", sales_amount=90_000.0, transaction_count=400),
            StateSales(state="WA", sales_amount=60_000.0, transaction_count=300),
        )
