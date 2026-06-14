"""Tests for the M4.4 e-commerce connector framework (sandbox, no network)."""

from __future__ import annotations

import unittest
from unittest import mock

from starlette.testclient import TestClient

from backend.connectors import (
    ConnectorNotConfigured,
    OAuthConfig,
    evaluate_connector_nexus,
    get_connector,
    list_connectors,
)
from backend.connectors.amazon import AmazonConnector
from backend.connectors.shopify import ShopifyConnector
from backend.main import app


class OAuthConfigTests(unittest.TestCase):
    def test_from_env_present(self):
        env = {
            "TAXGLOBAL_SHOPIFY_CLIENT_ID": "id",
            "TAXGLOBAL_SHOPIFY_CLIENT_SECRET": "secret",
            "TAXGLOBAL_SHOPIFY_REDIRECT_URI": "https://app/callback",
            "TAXGLOBAL_SHOPIFY_SCOPES": "read_orders, read_products",
        }
        with mock.patch.dict("os.environ", env, clear=False):
            cfg = OAuthConfig.from_env("TAXGLOBAL_SHOPIFY")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.client_id, "id")
        self.assertEqual(cfg.scopes, ("read_orders", "read_products"))

    def test_from_env_absent_returns_none(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(OAuthConfig.from_env("TAXGLOBAL_SHOPIFY"))

    def test_from_env_requires_redirect_uri(self):
        # id+secret without a redirect URI must NOT count as configured.
        env = {
            "TAXGLOBAL_SHOPIFY_CLIENT_ID": "id",
            "TAXGLOBAL_SHOPIFY_CLIENT_SECRET": "secret",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertIsNone(OAuthConfig.from_env("TAXGLOBAL_SHOPIFY"))


class ConnectorBehaviorTests(unittest.TestCase):
    def test_facilitator_flags(self):
        self.assertFalse(ShopifyConnector().is_marketplace_facilitator)
        self.assertTrue(AmazonConnector().is_marketplace_facilitator)

    def test_sandbox_result_has_sales(self):
        result = AmazonConnector().fetch_sales(sandbox=True)
        self.assertTrue(result.sandbox)
        self.assertGreater(result.total_sales, 0)
        self.assertTrue(any(s.state == "CA" for s in result.sales_by_state))

    def test_live_fetch_without_config_raises(self):
        with self.assertRaises(ConnectorNotConfigured):
            ShopifyConnector().fetch_sales(sandbox=False)

    def test_authorize_url_requires_config(self):
        with self.assertRaises(ConnectorNotConfigured):
            ShopifyConnector().authorize_url()

    def test_shopify_shop_substitution(self):
        oauth = OAuthConfig(
            client_id="cid",
            client_secret="sec",
            redirect_uri="https://app/cb",
            scopes=("read_orders",),
            shop="myshop",
        )
        url = ShopifyConnector(oauth=oauth).authorize_url()
        self.assertIn("myshop.myshopify.com", url)
        self.assertNotIn("{shop}", url)

    def test_shopify_without_shop_raises(self):
        oauth = OAuthConfig(client_id="cid", client_secret="sec", redirect_uri="https://app/cb")
        with self.assertRaises(ConnectorNotConfigured):
            ShopifyConnector(oauth=oauth).authorize_url()

    def test_authorize_url_builds_with_config(self):
        oauth = OAuthConfig(
            client_id="cid",
            client_secret="sec",
            redirect_uri="https://app/cb",
            scopes=("read_orders",),
        )
        url = AmazonConnector(oauth=oauth).authorize_url(state="xyz")
        self.assertIn(AmazonConnector.authorize_endpoint, url)
        self.assertIn("client_id=cid", url)
        self.assertIn("response_type=code", url)
        self.assertIn("state=xyz", url)


class RegistryTests(unittest.TestCase):
    def test_get_known_and_unknown(self):
        self.assertIsInstance(get_connector("shopify"), ShopifyConnector)
        with self.assertRaises(KeyError):
            get_connector("ebay")

    def test_list_connectors_shape(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            listing = list_connectors()
        platforms = {c["platform"] for c in listing}
        self.assertEqual(platforms, {"shopify", "amazon"})
        for entry in listing:
            self.assertIn("is_marketplace_facilitator", entry)
            self.assertFalse(entry["configured"])  # no env creds


class NexusBridgeTests(unittest.TestCase):
    def test_amazon_ca_exceeds_threshold(self):
        result = AmazonConnector().fetch_sales(sandbox=True)
        evaluation = evaluate_connector_nexus(result, tax_year=2025)
        self.assertTrue(evaluation["is_marketplace_facilitator"])
        ca = next(s for s in evaluation["states"] if s["state"] == "CA")
        self.assertEqual(ca["nexus"]["status"], "ok")
        # Amazon CA sandbox sales (600k) exceed CA's 500k threshold.
        self.assertTrue(ca["nexus"]["result"]["exceeded"])

    def test_shopify_ca_below_threshold(self):
        result = ShopifyConnector().fetch_sales(sandbox=True)
        evaluation = evaluate_connector_nexus(result, tax_year=2025)
        self.assertFalse(evaluation["is_marketplace_facilitator"])
        ca = next(s for s in evaluation["states"] if s["state"] == "CA")
        # Shopify CA sandbox sales (250k) are below CA's 500k threshold.
        self.assertFalse(ca["nexus"]["result"]["exceeded"])


class ConnectorRoutesTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_list_endpoint(self):
        resp = self.client.get("/api/connectors")
        self.assertEqual(resp.status_code, 200)
        platforms = {c["platform"] for c in resp.json()["connectors"]}
        self.assertEqual(platforms, {"shopify", "amazon"})

    def test_sandbox_nexus_endpoint(self):
        resp = self.client.post("/api/connectors/amazon/nexus", json={"tax_year": 2025, "sandbox": True})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["sandbox"])
        self.assertEqual(body["platform"], "amazon")
        self.assertTrue(any(s["state"] == "CA" for s in body["states"]))

    def test_unknown_platform_404(self):
        resp = self.client.post("/api/connectors/ebay/nexus", json={"sandbox": True})
        self.assertEqual(resp.status_code, 404)

    def test_authorize_not_configured(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            resp = self.client.get("/api/connectors/shopify/authorize")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["configured"])
        self.assertIsNone(body["authorize_url"])


if __name__ == "__main__":
    unittest.main()
