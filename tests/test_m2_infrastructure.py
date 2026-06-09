"""M2.1 infrastructure tests for graceful degradation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from backend import config
from backend.main import create_app


class M2InfrastructureTests(unittest.TestCase):
    def test_pg_tables_defined(self):
        from backend import models

        self.assertEqual(models.User.__tablename__, "users")
        self.assertEqual(models.Profile.__tablename__, "profiles")
        self.assertEqual(models.AuditLog.__tablename__, "audit_log")

    def test_neo4j_client_module(self):
        from backend.knowledge import neo4j_client

        self.assertIsNone(neo4j_client.get_driver())
        with self.assertRaises(RuntimeError):
            neo4j_client.run_query("RETURN 1")

    def test_chroma_module(self):
        from backend.knowledge import vector_store

        self.assertIsNone(vector_store.get_collection())
        self.assertFalse(vector_store.is_chroma_available())

    def test_embedder_module(self):
        from backend.knowledge import embedder

        self.assertFalse(embedder.is_embedder_available())
        with self.assertRaises(RuntimeError):
            embedder.embed_text("FEIE")

    def test_config_defaults(self):
        from backend import config

        self.assertIn("postgresql+asyncpg://", config.DATABASE_URL)
        self.assertTrue(config.NEO4J_URI.startswith("bolt://"))
        self.assertEqual(config.CHROMA_PERSIST_DIR, "data/chroma")
        self.assertEqual(config.EMBEDDING_MODEL, "BAAI/bge-small-zh-v1.5")

    def test_health_endpoint_degrades_gracefully(self):
        with (
            patch.object(config, "ENABLE_POSTGRES", False),
            patch.object(config, "ENABLE_NEO4J", False),
            patch.object(config, "ENABLE_CHROMA", False),
            TestClient(create_app()) as client,
        ):
            response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "stores": {
                    "postgresql": False,
                    "neo4j": False,
                    "chroma": False,
                    "embedder": False,
                    "llm": False,
                },
            },
        )

    def test_calc_api_still_works_with_stores_disabled(self):
        with (
            patch.object(config, "ENABLE_POSTGRES", False),
            patch.object(config, "ENABLE_NEO4J", False),
            patch.object(config, "ENABLE_CHROMA", False),
            TestClient(create_app()) as client,
        ):
            response = client.post(
                "/calc/federal-income",
                json={"gross_income": 120000, "filing_status": "single", "tax_year": 2025},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("result", body)


if __name__ == "__main__":
    unittest.main()
