"""M4.4 e-commerce connector framework.

Normalizes each platform's sales into ``{platform, facilitator, sales_by_state}``
and bridges it to the existing ``nexus_estimate`` engine. Sandbox mode returns
deterministic sample data so the whole flow (and its tests) run with no network
and no credentials; a real connection needs the seller's OAuth app credentials
(the documented external dependency, project plan v3.1 §6.4).
"""

from .base import (
    ConnectorError,
    ConnectorNotConfigured,
    ConnectorResult,
    EcommerceConnector,
    OAuthConfig,
    StateSales,
)
from .nexus_bridge import evaluate_connector_nexus
from .registry import CONNECTOR_TYPES, get_connector, list_connectors

__all__ = [
    "CONNECTOR_TYPES",
    "ConnectorError",
    "ConnectorNotConfigured",
    "ConnectorResult",
    "EcommerceConnector",
    "OAuthConfig",
    "StateSales",
    "evaluate_connector_nexus",
    "get_connector",
    "list_connectors",
]
