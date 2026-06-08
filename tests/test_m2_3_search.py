"""M2.3 GraphRAG search tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

from backend.knowledge import search
from backend.main import create_app


def _mock_chroma_result() -> dict[str, list[list[object]]]:
    return {
        "ids": [["us_2026_feie_maximum"]],
        "documents": [["foreign_earned_income_exclusion: For 2026, the maximum FEIE is $132,900."]],
        "distances": [[0.13]],
        "metadatas": [
            [
                {
                    "jurisdiction": "US",
                    "topic": "foreign_earned_income_exclusion",
                    "tax_year": 2026,
                    "source_ids": json.dumps(["irs_rp_2025_32", "irs_form_2555"]),
                }
            ]
        ],
    }


def _mock_graph_result() -> list[dict[str, object]]:
    return [
        {
            "id": "us_2026_feie_maximum",
            "jurisdictions": [{"code": "US", "name": "United States", "type": "federal"}],
            "topics": [{"id": "foreign_earned_income_exclusion", "name": "foreign_earned_income_exclusion"}],
            "sources": [
                {
                    "id": "irs_rp_2025_32",
                    "title": "Revenue Procedure 2025-32",
                    "url": "https://www.irs.gov/pub/irs-drop/rp-25-32.pdf",
                    "publisher": "Internal Revenue Service",
                }
            ],
        }
    ]


class TestVectorSearch(unittest.TestCase):
    def test_vector_search_returns_results(self):
        collection = Mock()
        collection.query.return_value = _mock_chroma_result()
        with (
            patch.object(search.vector_store, "is_chroma_available", return_value=True),
            patch.object(search.vector_store, "get_collection", return_value=collection),
            patch.object(search.embedder, "is_embedder_available", return_value=True),
            patch.object(search.embedder, "embed_text", return_value=[0.1, 0.2]),
        ):
            results = search.vector_search("FEIE", top_k=3)

        self.assertEqual(results[0]["knowledge_id"], "us_2026_feie_maximum")
        self.assertEqual(results[0]["score"], 0.87)
        self.assertEqual(results[0]["metadata"]["tax_year"], 2026)

    def test_vector_search_chroma_unavailable_returns_empty(self):
        with patch.object(search.vector_store, "is_chroma_available", return_value=False):
            self.assertEqual(search.vector_search("FEIE"), [])

    def test_vector_search_embedder_unavailable_returns_empty(self):
        with (
            patch.object(search.vector_store, "is_chroma_available", return_value=True),
            patch.object(search.embedder, "is_embedder_available", return_value=False),
        ):
            self.assertEqual(search.vector_search("FEIE"), [])

    def test_vector_search_runtime_failure_returns_empty(self):
        collection = Mock()
        collection.query.side_effect = RuntimeError("chroma failed")
        with (
            patch.object(search.vector_store, "is_chroma_available", return_value=True),
            patch.object(search.vector_store, "get_collection", return_value=collection),
            patch.object(search.embedder, "is_embedder_available", return_value=True),
            patch.object(search.embedder, "embed_text", return_value=[0.1]),
        ):
            self.assertEqual(search.vector_search("FEIE"), [])

    def test_vector_search_jurisdiction_filter_includes_federal(self):
        collection = Mock()
        collection.query.return_value = _mock_chroma_result()
        with (
            patch.object(search.vector_store, "is_chroma_available", return_value=True),
            patch.object(search.vector_store, "get_collection", return_value=collection),
            patch.object(search.embedder, "is_embedder_available", return_value=True),
            patch.object(search.embedder, "embed_text", return_value=[0.1]),
        ):
            search.vector_search("California tax", filters={"jurisdiction": "CA", "tax_year": 2026})

        where = collection.query.call_args.kwargs["where"]
        self.assertIn({"$or": [{"jurisdiction": "CA"}, {"jurisdiction": "US"}]}, where["$and"])
        self.assertIn({"tax_year": 2026}, where["$and"])

    def test_vector_search_normalizes_jurisdiction_to_uppercase(self):
        collection = Mock()
        collection.query.return_value = _mock_chroma_result()
        with (
            patch.object(search.vector_store, "is_chroma_available", return_value=True),
            patch.object(search.vector_store, "get_collection", return_value=collection),
            patch.object(search.embedder, "is_embedder_available", return_value=True),
            patch.object(search.embedder, "embed_text", return_value=[0.1]),
        ):
            search.vector_search("California tax", filters={"jurisdiction": "ca"})

        where = collection.query.call_args.kwargs["where"]
        self.assertEqual(where, {"$or": [{"jurisdiction": "CA"}, {"jurisdiction": "US"}]})


class TestGraphSearch(unittest.TestCase):
    def test_graph_search_returns_relationships(self):
        with (
            patch.object(search.neo4j_client, "is_neo4j_available", return_value=True),
            patch.object(search.neo4j_client, "run_query", return_value=_mock_graph_result()),
        ):
            expansions = search.graph_search(["us_2026_feie_maximum"])

        self.assertIn("us_2026_feie_maximum", expansions)
        self.assertEqual(expansions["us_2026_feie_maximum"]["sources"][0]["source_id"], "irs_rp_2025_32")

    def test_graph_search_neo4j_unavailable_returns_empty(self):
        with patch.object(search.neo4j_client, "is_neo4j_available", return_value=False):
            self.assertEqual(search.graph_search(["x"]), {})

    def test_graph_search_batched_single_query(self):
        with (
            patch.object(search.neo4j_client, "is_neo4j_available", return_value=True),
            patch.object(search.neo4j_client, "run_query", return_value=[]) as run_query,
        ):
            search.graph_search(["a", "b", "c"])

        run_query.assert_called_once()
        self.assertIn("UNWIND $ids", run_query.call_args.args[0])
        self.assertEqual(run_query.call_args.args[1], {"ids": ["a", "b", "c"]})

    def test_graph_search_runtime_failure_returns_empty(self):
        with (
            patch.object(search.neo4j_client, "is_neo4j_available", return_value=True),
            patch.object(search.neo4j_client, "run_query", side_effect=RuntimeError("neo4j failed")),
        ):
            self.assertEqual(search.graph_search(["us_2026_feie_maximum"]), {})


class TestHybridSearch(unittest.TestCase):
    def test_hybrid_returns_merged_results(self):
        with (
            patch.object(search, "vector_search", return_value=_vector_hit()),
            patch.object(search, "graph_search", return_value=_graph_expansion()),
        ):
            response = search.hybrid_search("FEIE", tax_year=2026)

        result = response["results"][0]
        self.assertEqual(response["query_metadata"]["retrieval_method"], "hybrid")
        self.assertEqual(result["knowledge_id"], "us_2026_feie_maximum")
        self.assertEqual(result["sources"][0]["source_id"], "irs_rp_2025_32")
        self.assertEqual(result["topics"], ["foreign_earned_income_exclusion"])

    def test_hybrid_vector_only_degradation(self):
        with (
            patch.object(search, "vector_search", return_value=_vector_hit()),
            patch.object(search, "graph_search", return_value={}),
        ):
            response = search.hybrid_search("FEIE")

        self.assertEqual(response["query_metadata"]["retrieval_method"], "vector_only")
        self.assertEqual(response["results"][0]["sources"][0]["source_id"], "irs_rp_2025_32")

    def test_hybrid_filters_empty_graph_sources_and_falls_back(self):
        bad_graph = _graph_expansion()
        bad_graph["us_2026_feie_maximum"]["sources"] = [{"source_id": None, "title": "bad"}]
        with (
            patch.object(search, "vector_search", return_value=_vector_hit()),
            patch.object(search, "graph_search", return_value=bad_graph),
        ):
            response = search.hybrid_search("FEIE")

        self.assertEqual(response["results"][0]["sources"][0]["source_id"], "irs_rp_2025_32")

    def test_hybrid_chroma_down_returns_empty(self):
        with patch.object(search, "vector_search", return_value=[]):
            response = search.hybrid_search("FEIE")

        self.assertEqual(response["results"], [])
        self.assertEqual(response["total"], 0)
        self.assertEqual(response["query_metadata"]["retrieval_method"], "none")

    def test_hybrid_both_unavailable_returns_empty(self):
        with (
            patch.object(search, "vector_search", return_value=[]),
            patch.object(search, "graph_search", return_value={}),
        ):
            response = search.hybrid_search("FEIE")

        self.assertEqual(response["results"], [])
        self.assertEqual(response["total"], 0)
        self.assertEqual(response["query_metadata"]["retrieval_method"], "none")

    def test_hybrid_clamps_top_k(self):
        with patch.object(search, "vector_search", return_value=[]) as vector_search:
            search.hybrid_search("FEIE", top_k=100)

        self.assertEqual(vector_search.call_args.kwargs["top_k"], search.MAX_TOP_K)


def _empty_search_response() -> dict[str, object]:
    return {
        "results": [],
        "total": 0,
        "query_metadata": {
            "vector_hits": 0,
            "graph_expansions": 0,
            "retrieval_method": "none",
        },
    }


class TestSearchRoute(unittest.TestCase):
    def test_search_endpoint_returns_200(self):
        with (
            patch("backend.config.ENABLE_POSTGRES", False),
            patch("backend.config.ENABLE_NEO4J", False),
            patch("backend.config.ENABLE_CHROMA", False),
            patch("backend.knowledge.search_routes.hybrid_search", return_value=_empty_search_response()),
            TestClient(create_app()) as client,
        ):
            response = client.get("/api/knowledge/search?q=FEIE")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)

    def test_search_missing_query_returns_422(self):
        with (
            patch("backend.config.ENABLE_POSTGRES", False),
            patch("backend.config.ENABLE_NEO4J", False),
            patch("backend.config.ENABLE_CHROMA", False),
            TestClient(create_app()) as client,
        ):
            response = client.get("/api/knowledge/search")

        self.assertEqual(response.status_code, 422)

    def test_search_with_filters(self):
        with (
            patch("backend.config.ENABLE_POSTGRES", False),
            patch("backend.config.ENABLE_NEO4J", False),
            patch("backend.config.ENABLE_CHROMA", False),
            patch("backend.knowledge.search_routes.hybrid_search", return_value=_empty_search_response()) as hs,
            TestClient(create_app()) as client,
        ):
            client.get("/api/knowledge/search?q=FEIE&jurisdiction=US&tax_year=2026&top_k=7")

        self.assertEqual(hs.call_args.kwargs["query"], "FEIE")
        self.assertEqual(hs.call_args.kwargs["jurisdiction"], "US")
        self.assertEqual(hs.call_args.kwargs["tax_year"], 2026)
        self.assertEqual(hs.call_args.kwargs["top_k"], 7)

    def test_search_empty_results(self):
        with (
            patch("backend.config.ENABLE_POSTGRES", False),
            patch("backend.config.ENABLE_NEO4J", False),
            patch("backend.config.ENABLE_CHROMA", False),
            patch("backend.knowledge.search_routes.hybrid_search", return_value=_empty_search_response()),
            TestClient(create_app()) as client,
        ):
            response = client.get("/api/knowledge/search?q=nothing")

        body = response.json()
        self.assertEqual(body["results"], [])
        self.assertEqual(body["total"], 0)


class TestSearchDataIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        knowledge = json.loads(Path("data/knowledge/us/2026/us_core_knowledge.json").read_text(encoding="utf-8"))
        manifest = json.loads(Path("data/sources/us/2026/source_manifest.json").read_text(encoding="utf-8"))
        cls.items = knowledge["items"]
        cls.sources = {source["source_id"]: source for source in manifest["sources"]}

    def test_knowledge_items_searchable_format(self):
        for item in self.items:
            self.assertTrue(item["knowledge_id"])
            self.assertTrue(item["topic"])
            self.assertTrue(item["jurisdiction"])
            self.assertTrue(item["summary"])
            self.assertTrue(item["source_ids"])

    def test_source_manifest_has_urls(self):
        referenced = {source_id for item in self.items for source_id in item["source_ids"]}
        missing = [
            source_id for source_id in sorted(referenced)
            if source_id not in self.sources or not self.sources[source_id].get("source_url")
        ]
        self.assertEqual(missing, [])

    def test_minimum_topic_diversity(self):
        topics = {item["topic"] for item in self.items}
        self.assertGreaterEqual(len(topics), 8)


def _vector_hit() -> list[dict[str, object]]:
    return [
        {
            "knowledge_id": "us_2026_feie_maximum",
            "content": "foreign_earned_income_exclusion: For 2026, the maximum FEIE is $132,900.",
            "score": 0.87,
            "metadata": {
                "jurisdiction": "US",
                "topic": "foreign_earned_income_exclusion",
                "tax_year": 2026,
                "source_ids": json.dumps(["irs_rp_2025_32", "irs_form_2555"]),
            },
        }
    ]


def _graph_expansion() -> dict[str, dict[str, object]]:
    return {
        "us_2026_feie_maximum": {
            "jurisdictions": [{"code": "US", "name": "United States", "type": "federal"}],
            "topics": [{"id": "foreign_earned_income_exclusion", "name": "foreign_earned_income_exclusion"}],
            "sources": [
                {
                    "source_id": "irs_rp_2025_32",
                    "title": "Revenue Procedure 2025-32",
                    "url": "https://www.irs.gov/pub/irs-drop/rp-25-32.pdf",
                    "publisher": "Internal Revenue Service",
                }
            ],
        }
    }


if __name__ == "__main__":
    unittest.main()
