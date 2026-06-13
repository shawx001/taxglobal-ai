"""Tests for Phase C.1 cross-encoder reranking in hybrid_search."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import backend.config as cfg
from backend.knowledge import reranker, search


def _hit(kid: str, content: str, score: float) -> dict:
    return {
        "knowledge_id": kid,
        "content": content,
        "score": score,
        "metadata": {"source_ids": f'["src_{kid}"]', "jurisdiction": "US", "tax_year": 2025},
    }


class _FakeReranker:
    """Reranks by a fixed score map keyed on substring; available=True."""

    def __init__(self, score_by_kid: dict[str, float]) -> None:
        self._by_kid = score_by_kid

    def is_reranker_available(self) -> bool:
        return True

    def rerank_scores(self, query: str, passages: list[str]) -> list[float]:
        scores = []
        for passage in passages:
            scores.append(next((v for k, v in self._by_kid.items() if k in passage), 0.0))
        return scores


class TestRerankerModule(unittest.TestCase):
    def test_unavailable_raises_and_reports_false(self) -> None:
        reranker.close_reranker()
        self.assertFalse(reranker.is_reranker_available())
        with self.assertRaises(RuntimeError):
            reranker.rerank_scores("q", ["a"])

    def test_disabled_flag_skips_load(self) -> None:
        saved = cfg.ENABLE_RERANK
        try:
            cfg.ENABLE_RERANK = False
            reranker.close_reranker()
            reranker.init_reranker()
            self.assertFalse(reranker.is_reranker_available())
        finally:
            cfg.ENABLE_RERANK = saved
            reranker.close_reranker()


class TestHybridSearchRerank(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (cfg.ENABLE_RERANK, cfg.RERANK_POOL)
        cfg.ENABLE_RERANK = True
        cfg.RERANK_POOL = 20

    def tearDown(self) -> None:
        (cfg.ENABLE_RERANK, cfg.RERANK_POOL) = self._saved

    def test_rerank_reorders_against_vector_order(self) -> None:
        # Vector order would rank A>B>C; the reranker flips it to C>B>A.
        vector_hits = [_hit("A", "alpha", 0.9), _hit("B", "beta", 0.8), _hit("C", "gamma", 0.7)]
        fake = _FakeReranker({"alpha": 0.1, "beta": 0.5, "gamma": 0.99})
        with (
            patch.object(search, "vector_search", return_value=vector_hits),
            patch.object(search, "graph_search", return_value={}),
            patch.object(search.reranker, "is_reranker_available", fake.is_reranker_available),
            patch.object(search.reranker, "rerank_scores", fake.rerank_scores),
        ):
            out = search.hybrid_search("q", top_k=3)
        self.assertTrue(out["query_metadata"]["reranked"])
        self.assertEqual([r["knowledge_id"] for r in out["results"]], ["C", "B", "A"])
        self.assertEqual(out["results"][0]["rerank_score"], 0.99)
        # Vector score is preserved alongside the rerank score.
        self.assertEqual(out["results"][0]["score"], 0.7)

    def test_top_k_trim_after_rerank(self) -> None:
        vector_hits = [_hit(k, k.lower(), 0.5) for k in ["A", "B", "C", "D", "E"]]
        fake = _FakeReranker({"a": 0.1, "b": 0.2, "c": 0.9, "d": 0.8, "e": 0.3})
        with (
            patch.object(search, "vector_search", return_value=vector_hits),
            patch.object(search, "graph_search", return_value={}),
            patch.object(search.reranker, "is_reranker_available", fake.is_reranker_available),
            patch.object(search.reranker, "rerank_scores", fake.rerank_scores),
        ):
            out = search.hybrid_search("q", top_k=2)
        self.assertEqual([r["knowledge_id"] for r in out["results"]], ["C", "D"])
        self.assertEqual(out["total"], 2)

    def test_degrades_to_vector_order_when_unavailable(self) -> None:
        vector_hits = [_hit("A", "alpha", 0.9), _hit("B", "beta", 0.7)]
        with (
            patch.object(search, "vector_search", return_value=vector_hits),
            patch.object(search, "graph_search", return_value={}),
            patch.object(search.reranker, "is_reranker_available", lambda: False),
        ):
            out = search.hybrid_search("q", top_k=2)
        self.assertFalse(out["query_metadata"]["reranked"])
        self.assertEqual([r["knowledge_id"] for r in out["results"]], ["A", "B"])
        self.assertIsNone(out["results"][0]["rerank_score"])

    def test_rerank_exception_falls_back_to_vector_order(self) -> None:
        vector_hits = [_hit("A", "alpha", 0.9), _hit("B", "beta", 0.7)]

        def _boom(query, passages):
            raise RuntimeError("model crash")

        with (
            patch.object(search, "vector_search", return_value=vector_hits),
            patch.object(search, "graph_search", return_value={}),
            patch.object(search.reranker, "is_reranker_available", lambda: True),
            patch.object(search.reranker, "rerank_scores", _boom),
        ):
            out = search.hybrid_search("q", top_k=2)
        self.assertFalse(out["query_metadata"]["reranked"])
        self.assertEqual([r["knowledge_id"] for r in out["results"]], ["A", "B"])

    def test_score_count_mismatch_falls_back(self) -> None:
        vector_hits = [_hit("A", "alpha", 0.9), _hit("B", "beta", 0.7)]
        with (
            patch.object(search, "vector_search", return_value=vector_hits),
            patch.object(search, "graph_search", return_value={}),
            patch.object(search.reranker, "is_reranker_available", lambda: True),
            patch.object(search.reranker, "rerank_scores", lambda q, p: [0.5]),  # wrong length
        ):
            out = search.hybrid_search("q", top_k=2)
        self.assertFalse(out["query_metadata"]["reranked"])
        self.assertEqual([r["knowledge_id"] for r in out["results"]], ["A", "B"])

    def test_disabled_flag_uses_vector_order_and_narrow_pool(self) -> None:
        cfg.ENABLE_RERANK = False
        captured = {}

        def _capture_vector(query, top_k, filters=None):
            captured["top_k"] = top_k
            return [_hit("A", "alpha", 0.9)]

        with (
            patch.object(search, "vector_search", _capture_vector),
            patch.object(search, "graph_search", return_value={}),
        ):
            out = search.hybrid_search("q", top_k=3)
        self.assertFalse(out["query_metadata"]["reranked"])
        self.assertEqual(captured["top_k"], 3)  # narrow pool when rerank off

    def test_wider_pool_retrieved_when_reranking(self) -> None:
        captured = {}

        def _capture_vector(query, top_k, filters=None):
            captured["top_k"] = top_k
            return [_hit("A", "alpha", 0.9)]

        fake = _FakeReranker({"alpha": 0.9})
        with (
            patch.object(search, "vector_search", _capture_vector),
            patch.object(search, "graph_search", return_value={}),
            patch.object(search.reranker, "is_reranker_available", fake.is_reranker_available),
            patch.object(search.reranker, "rerank_scores", fake.rerank_scores),
        ):
            search.hybrid_search("q", top_k=3)
        self.assertEqual(captured["top_k"], 20)  # RERANK_POOL


if __name__ == "__main__":
    unittest.main()
