"""Tests for Phase C.3 Neo4j multi-hop related-rule expansion.

Neo4j is not running in this environment, so graph_search is exercised
with a mocked run_query (the Cypher itself is verified live only once a
Neo4j instance is available — same caveat as W-2 vision).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import backend.config as cfg
from backend.knowledge import search


class TestGraphSearchRelatedRules(unittest.TestCase):
    def test_parses_related_rules(self) -> None:
        rows = [
            {
                "id": "rule_A",
                "jurisdictions": [],
                "topics": [{"id": "feie", "name": "FEIE"}],
                "sources": [],
                "related_rules": [
                    {"id": "rule_B", "title": "Bona fide residence"},
                    {"id": "rule_C", "title": "Physical presence test"},
                ],
            }
        ]
        with (
            patch.object(search.neo4j_client, "is_neo4j_available", lambda: True),
            patch.object(search.neo4j_client, "run_query", return_value=rows),
        ):
            out = search.graph_search(["rule_A"])
        self.assertEqual(
            out["rule_A"]["related_rules"],
            [
                {"id": "rule_B", "title": "Bona fide residence"},
                {"id": "rule_C", "title": "Physical presence test"},
            ],
        )

    def test_drops_related_without_id(self) -> None:
        rows = [
            {
                "id": "rule_A",
                "jurisdictions": [],
                "topics": [],
                "sources": [],
                "related_rules": [{"id": None, "title": "broken"}, {"id": "rule_B", "title": "ok"}, None],
            }
        ]
        with (
            patch.object(search.neo4j_client, "is_neo4j_available", lambda: True),
            patch.object(search.neo4j_client, "run_query", return_value=rows),
        ):
            out = search.graph_search(["rule_A"])
        self.assertEqual(out["rule_A"]["related_rules"], [{"id": "rule_B", "title": "ok"}])

    def test_missing_related_rules_key_yields_empty(self) -> None:
        rows = [{"id": "rule_A", "jurisdictions": [], "topics": [], "sources": []}]
        with (
            patch.object(search.neo4j_client, "is_neo4j_available", lambda: True),
            patch.object(search.neo4j_client, "run_query", return_value=rows),
        ):
            out = search.graph_search(["rule_A"])
        self.assertEqual(out["rule_A"]["related_rules"], [])

    def test_none_valued_fields_do_not_crash(self) -> None:
        """A present-but-None facet value must coalesce to [], not raise."""
        rows = [
            {"id": "rule_A", "jurisdictions": None, "topics": None, "sources": None, "related_rules": None}
        ]
        with (
            patch.object(search.neo4j_client, "is_neo4j_available", lambda: True),
            patch.object(search.neo4j_client, "run_query", return_value=rows),
        ):
            out = search.graph_search(["rule_A"])
        self.assertEqual(out["rule_A"]["related_rules"], [])
        self.assertEqual(out["rule_A"]["topics"], [])
        self.assertEqual(out["rule_A"]["sources"], [])
        self.assertEqual(out["rule_A"]["jurisdictions"], [])

    def test_passes_related_limit_param(self) -> None:
        captured = {}

        def _capture(cypher, params):
            captured["params"] = params
            return []

        saved = cfg.GRAPH_RELATED_LIMIT
        try:
            cfg.GRAPH_RELATED_LIMIT = 7
            with (
                patch.object(search.neo4j_client, "is_neo4j_available", lambda: True),
                patch.object(search.neo4j_client, "run_query", _capture),
            ):
                search.graph_search(["rule_A"])
            self.assertEqual(captured["params"]["max_related"], 7)
        finally:
            cfg.GRAPH_RELATED_LIMIT = saved

    def test_neo4j_unavailable_returns_empty(self) -> None:
        with patch.object(search.neo4j_client, "is_neo4j_available", lambda: False):
            self.assertEqual(search.graph_search(["rule_A"]), {})

    def test_query_failure_degrades(self) -> None:
        def _boom(cypher, params):
            raise RuntimeError("neo4j down")

        with (
            patch.object(search.neo4j_client, "is_neo4j_available", lambda: True),
            patch.object(search.neo4j_client, "run_query", _boom),
        ):
            self.assertEqual(search.graph_search(["rule_A"]), {})


def _hit(kid: str, content: str, score: float) -> dict:
    return {
        "knowledge_id": kid,
        "content": content,
        "score": score,
        "metadata": {"source_ids": f'["src_{kid}"]', "jurisdiction": "US"},
    }


class TestHybridSearchSurfacesRelatedRules(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = cfg.ENABLE_RERANK
        cfg.ENABLE_RERANK = False  # isolate graph behavior from reranking

    def tearDown(self) -> None:
        cfg.ENABLE_RERANK = self._saved

    def test_related_rules_surface_into_results(self) -> None:
        expansions = {
            "A": {
                "jurisdictions": [],
                "topics": [],
                "sources": [{"source_id": "src_A", "title": None, "url": None, "publisher": None}],
                "related_rules": [{"id": "B", "title": "Sibling rule"}],
            }
        }
        with (
            patch.object(search, "vector_search", return_value=[_hit("A", "alpha", 0.9)]),
            patch.object(search, "graph_search", return_value=expansions),
        ):
            out = search.hybrid_search("q", top_k=3)
        self.assertEqual(out["results"][0]["related_rules"], [{"id": "B", "title": "Sibling rule"}])

    def test_no_graph_data_yields_empty_related_rules(self) -> None:
        with (
            patch.object(search, "vector_search", return_value=[_hit("A", "alpha", 0.9)]),
            patch.object(search, "graph_search", return_value={}),
        ):
            out = search.hybrid_search("q", top_k=3)
        self.assertEqual(out["results"][0]["related_rules"], [])


if __name__ == "__main__":
    unittest.main()
