"""Connector base types: normalized result, OAuth config, and the ABC.

Every platform reduces to a ``ConnectorResult`` so downstream nexus logic is
platform-agnostic. OAuth follows the standard redirect flow (authorize URL ->
callback code -> token exchange); without configured credentials a connector can
still serve **sandbox** sample data, but a live fetch fails loudly rather than
fabricating sales.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlencode


class ConnectorError(Exception):
    """Base error for connector operations."""


class ConnectorNotConfigured(ConnectorError):
    """Raised when a live operation needs OAuth credentials that are absent."""


@dataclass(frozen=True)
class StateSales:
    """Sales aggregated for one state."""

    state: str
    sales_amount: float
    transaction_count: int


@dataclass(frozen=True)
class ConnectorResult:
    """Normalized, platform-agnostic sales snapshot."""

    platform: str
    is_marketplace_facilitator: bool
    sales_by_state: tuple[StateSales, ...]
    sandbox: bool = False

    @property
    def total_sales(self) -> float:
        return float(sum(s.sales_amount for s in self.sales_by_state))

    def as_dict(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "is_marketplace_facilitator": self.is_marketplace_facilitator,
            "sandbox": self.sandbox,
            "total_sales": self.total_sales,
            "sales_by_state": [
                {"state": s.state, "sales_amount": s.sales_amount, "transaction_count": s.transaction_count}
                for s in self.sales_by_state
            ],
        }


@dataclass(frozen=True)
class OAuthConfig:
    """OAuth client credentials + redirect (per seller install)."""

    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...] = ()
    shop: str = ""  # platform-specific tenant (e.g. a Shopify shop subdomain)

    @classmethod
    def from_env(cls, prefix: str) -> OAuthConfig | None:
        """Build from ``{PREFIX}_CLIENT_ID`` etc.

        Returns ``None`` unless the universal OAuth essentials — client id,
        secret AND redirect URI — are all present, so a half-configured connector
        never advertises itself as ready with an unusable authorize URL.
        """

        client_id = os.environ.get(f"{prefix}_CLIENT_ID")
        client_secret = os.environ.get(f"{prefix}_CLIENT_SECRET")
        redirect_uri = os.environ.get(f"{prefix}_REDIRECT_URI")
        if not (client_id and client_secret and redirect_uri):
            return None
        scopes = tuple(s.strip() for s in os.environ.get(f"{prefix}_SCOPES", "").split(",") if s.strip())
        shop = os.environ.get(f"{prefix}_SHOP", "")
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scopes=scopes,
            shop=shop,
        )


class EcommerceConnector(ABC):
    """A read-only sales connector for one platform.

    Subclasses set the platform identity, facilitator status, OAuth endpoints,
    and provide sandbox sample data + (scaffolded) live fetch.
    """

    platform: str = ""
    is_marketplace_facilitator: bool = False
    authorize_endpoint: str = ""
    token_endpoint: str = ""
    default_scopes: tuple[str, ...] = ()

    def __init__(self, oauth: OAuthConfig | None = None) -> None:
        self.oauth = oauth

    @property
    def configured(self) -> bool:
        return self.oauth is not None

    def _format_endpoint(self, endpoint: str) -> str:
        """Substitute platform tenant placeholders (e.g. Shopify ``{shop}``)."""

        if "{shop}" in endpoint:
            shop = self.oauth.shop if self.oauth else ""
            if not shop:
                raise ConnectorNotConfigured(f"{self.platform} requires a shop domain; set {self.env_prefix()}_SHOP")
            endpoint = endpoint.replace("{shop}", shop)
        return endpoint

    def authorize_url(self, *, state: str = "") -> str:
        """Build the OAuth authorize redirect URL (the 'jump to platform' step)."""

        if self.oauth is None:
            raise ConnectorNotConfigured(
                f"{self.platform} OAuth is not configured; set {self.env_prefix()}_CLIENT_ID/_CLIENT_SECRET"
            )
        scopes = self.oauth.scopes or self.default_scopes
        params = {
            "client_id": self.oauth.client_id,
            "redirect_uri": self.oauth.redirect_uri,
            "response_type": "code",
            "scope": ",".join(scopes),
        }
        if state:
            params["state"] = state
        return f"{self._format_endpoint(self.authorize_endpoint)}?{urlencode(params)}"

    def env_prefix(self) -> str:
        return f"TAXGLOBAL_{self.platform.upper()}"

    def exchange_code(self, code: str) -> str:  # pragma: no cover - needs live network
        """Exchange an authorization code for an access token.

        Scaffolded: the real token POST needs configured credentials and network
        access to the platform; raise loudly until those are provided.
        """

        if self.oauth is None:
            raise ConnectorNotConfigured(f"{self.platform} OAuth is not configured")
        raise ConnectorNotConfigured(
            f"{self.platform} live token exchange requires platform network access and approved app credentials"
        )

    def fetch_sales(self, *, sandbox: bool = True, token: str | None = None) -> ConnectorResult:
        """Return normalized sales. ``sandbox`` yields deterministic sample data."""

        if sandbox:
            return self.sandbox_result()
        return self._fetch_live(token)

    def sandbox_result(self) -> ConnectorResult:
        return ConnectorResult(
            platform=self.platform,
            is_marketplace_facilitator=self.is_marketplace_facilitator,
            sales_by_state=self._sandbox_sales(),
            sandbox=True,
        )

    def _fetch_live(self, token: str | None) -> ConnectorResult:  # pragma: no cover - needs live network
        raise ConnectorNotConfigured(
            f"{self.platform} live sales fetch requires approved app credentials and platform network access; "
            "use sandbox=True for sample data"
        )

    @abstractmethod
    def _sandbox_sales(self) -> tuple[StateSales, ...]:
        """Deterministic sample sales for sandbox mode."""
