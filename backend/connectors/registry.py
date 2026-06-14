"""Connector registry: resolve a platform name to a connector instance."""

from __future__ import annotations

from .amazon import AmazonConnector
from .base import EcommerceConnector, OAuthConfig
from .shopify import ShopifyConnector

CONNECTOR_TYPES: dict[str, type[EcommerceConnector]] = {
    ShopifyConnector.platform: ShopifyConnector,
    AmazonConnector.platform: AmazonConnector,
}


def get_connector(platform: str, oauth: OAuthConfig | None = None) -> EcommerceConnector:
    """Instantiate a connector by platform name.

    If ``oauth`` is omitted, credentials are read from the platform's env prefix
    (``TAXGLOBAL_<PLATFORM>_CLIENT_ID`` ...); absent credentials leave the
    connector in sandbox-only mode.
    """

    key = platform.strip().lower()
    connector_type = CONNECTOR_TYPES.get(key)
    if connector_type is None:
        raise KeyError(f"unknown connector platform {platform!r}; known: {sorted(CONNECTOR_TYPES)}")
    if oauth is None:
        oauth = OAuthConfig.from_env(f"TAXGLOBAL_{key.upper()}")
    return connector_type(oauth=oauth)


def list_connectors() -> list[dict[str, object]]:
    """List available connectors with their facilitator + configured status."""

    result: list[dict[str, object]] = []
    for key, connector_type in CONNECTOR_TYPES.items():
        connector = get_connector(key)
        result.append(
            {
                "platform": key,
                "is_marketplace_facilitator": connector_type.is_marketplace_facilitator,
                "configured": connector.configured,
            }
        )
    return result
