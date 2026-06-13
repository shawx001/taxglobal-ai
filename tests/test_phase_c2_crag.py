"""Tests for Phase C.2 Corrective RAG relevance grading."""

from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import backend.config as cfg
from backend.knowledge import crag, search


def _logit(sigmoid_target: float) -> float:
    """Inverse sigmoid: rerank_score whose sigmoid equals the target."""
    return math.log(sigmoid_target / (1 - sigmoid_target))


def _graded_hit(kid: str, sigmoid_rel: float) -> dict:
    return {"knowledge_id": kid, "rerank_score": _logit(sigmoid_rel)}


class TestGradeHits(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (cfg.ENABLE_CRAG, cfg.CRAG_RELEVANT, cfg.CRAG_AMBIGUOUS)
        cfg.ENABLE_CRAG = True
        cfg.CRAG_RELEVANT = 0.5
        cfg.CRAG_AMBIGUOUS = 0.2

    def tearDown(self) -> None:
        (cfg.ENABLE_CRAG, cfg.CRAG_RELEVANT, cfg.CRAG_AMBIGUOUS) = self._saved

    def test_unknown_when_not_reranked(self) -> None:
        hits = [_graded_hit("A", 0.9)]
        confidence, kept = crag.grade_hits(hits, reranked=False)
        self.assertEqual(confidence, "unknown")
        self.assertEqual(kept, hits)  # nothing dropped

    def test_high_confidence_keeps_relevant(self) -> None:
        hits = [_graded_hit("A", 0.95), _graded_hit("B", 0.6)]
        confidence, kept = crag.grade_hits(hits, reranked=True)
        self.assertEqual(confidence, "high")
        self.assertEqual([h["knowledge_id"] for h in kept], ["A", "B"])
        self.assertAlmostEqual(kept[0]["relevance"], 0.95, places=4)

    def test_medium_confidence(self) -> None:
        hits = [_graded_hit("A", 0.35)]
        confidence, kept = crag.grade_hits(hits, reranked=True)
        self.assertEqual(confidence, "medium")
        self.assertEqual(len(kept), 1)

    def test_low_confidence_drops_everything(self) -> None:
        hits = [_graded_hit("A", 0.1), _graded_hit("B", 0.05)]
        confidence, kept = crag.grade_hits(hits, reranked=True)
        self.assertEqual(confidence, "low")
        self.assertEqual(kept, [])  # nothing relevant → honest empty

    def test_high_top_still_drops_irrelevant_tail(self) -> None:
        hits = [_graded_hit("A", 0.95), _graded_hit("B", 0.05)]
        confidence, kept = crag.grade_hits(hits, reranked=True)
        self.assertEqual(confidence, "high")
        self.assertEqual([h["knowledge_id"] for h in kept], ["A"])  # B dropped

    def test_disabled_flag_is_noop(self) -> None:
        cfg.ENABLE_CRAG = False
        hits = [_graded_hit("A", 0.01)]
        confidence, kept = crag.grade_hits(hits, reranked=True)
        self.assertEqual(confidence, "unknown")
        self.assertEqual(kept, hits)

    def test_empty_hits(self) -> None:
        confidence, kept = crag.grade_hits([], reranked=True)
        self.assertEqual(confidence, "unknown")
        self.assertEqual(kept, [])

    def test_missing_rerank_score_treated_irrelevant(self) -> None:
        hits = [{"knowledge_id": "A"}]  # no rerank_score
        confidence, kept = crag.grade_hits(hits, reranked=True)
        self.assertEqual(confidence, "low")
        self.assertEqual(kept, [])

    def test_inverted_thresholds_fail_safe(self) -> None:
        """Misconfig AMBIGUOUS > RELEVANT must not produce high+empty."""
        cfg.CRAG_RELEVANT = 0.2
        cfg.CRAG_AMBIGUOUS = 0.5
        hits = [_graded_hit("A", 0.35)]  # >=RELEVANT but <AMBIGUOUS → dropped
        confidence, kept = crag.grade_hits(hits, reranked=True)
        self.assertEqual(kept, [])
        self.assertEqual(confidence, "low")  # label follows the kept set


def _hit(kid: str, content: str, score: float) -> dict:
    return {
        "knowledge_id": kid,
        "content": content,
        "score": score,
        "metadata": {"source_ids": f'["src_{kid}"]', "jurisdiction": "US", "tax_year": 2025},
    }


class _FakeReranker:
    def __init__(self, logit_by_kid: dict[str, float]) -> None:
        self._by = logit_by_kid

    def is_reranker_available(self) -> bool:
        return True

    def rerank_scores(self, query: str, passages: list[str]) -> list[float]:
        return [next((v for k, v in self._by.items() if k in p), -10.0) for p in passages]


class TestHybridSearchCrag(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (cfg.ENABLE_RERANK, cfg.ENABLE_CRAG, cfg.CRAG_RELEVANT, cfg.CRAG_AMBIGUOUS, cfg.RERANK_POOL)
        cfg.ENABLE_RERANK = True
        cfg.ENABLE_CRAG = True
        cfg.CRAG_RELEVANT = 0.5
        cfg.CRAG_AMBIGUOUS = 0.2
        cfg.RERANK_POOL = 20

    def tearDown(self) -> None:
        (cfg.ENABLE_RERANK, cfg.ENABLE_CRAG, cfg.CRAG_RELEVANT, cfg.CRAG_AMBIGUOUS, cfg.RERANK_POOL) = self._saved

    def test_low_relevance_yields_empty_results_low_confidence(self) -> None:
        vector_hits = [_hit("A", "alpha", 0.9), _hit("B", "beta", 0.8)]
        fake = _FakeReranker({"alpha": _logit(0.08), "beta": _logit(0.05)})
        with (
            patch.object(search, "vector_search", return_value=vector_hits),
            patch.object(search, "graph_search", return_value={}),
            patch.object(search.reranker, "is_reranker_available", fake.is_reranker_available),
            patch.object(search.reranker, "rerank_scores", fake.rerank_scores),
        ):
            out = search.hybrid_search("q", top_k=5)
        self.assertEqual(out["results"], [])
        self.assertEqual(out["total"], 0)
        self.assertEqual(out["query_metadata"]["confidence"], "low")

    def test_relevant_results_high_confidence_with_relevance_field(self) -> None:
        vector_hits = [_hit("A", "alpha", 0.5), _hit("B", "beta", 0.4)]
        fake = _FakeReranker({"alpha": _logit(0.95), "beta": _logit(0.7)})
        with (
            patch.object(search, "vector_search", return_value=vector_hits),
            patch.object(search, "graph_search", return_value={}),
            patch.object(search.reranker, "is_reranker_available", fake.is_reranker_available),
            patch.object(search.reranker, "rerank_scores", fake.rerank_scores),
        ):
            out = search.hybrid_search("q", top_k=5)
        self.assertEqual(out["query_metadata"]["confidence"], "high")
        self.assertEqual([r["knowledge_id"] for r in out["results"]], ["A", "B"])
        self.assertAlmostEqual(out["results"][0]["relevance"], 0.95, places=3)

    def test_high_relevance_but_no_sources_yields_empty_low(self) -> None:
        """A relevant hit dropped for lacking sources must not leave a
        'high confidence, 0 results' state — the label follows results."""
        hit = {"knowledge_id": "A", "content": "alpha", "score": 0.5, "metadata": {"source_ids": "[]"}}
        fake = _FakeReranker({"alpha": _logit(0.95)})
        with (
            patch.object(search, "vector_search", return_value=[hit]),
            patch.object(search, "graph_search", return_value={}),
            patch.object(search.reranker, "is_reranker_available", fake.is_reranker_available),
            patch.object(search.reranker, "rerank_scores", fake.rerank_scores),
        ):
            out = search.hybrid_search("q", top_k=5)
        self.assertEqual(out["results"], [])
        self.assertEqual(out["query_metadata"]["confidence"], "low")

    def test_unknown_confidence_when_not_reranked(self) -> None:
        vector_hits = [_hit("A", "alpha", 0.9)]
        with (
            patch.object(search, "vector_search", return_value=vector_hits),
            patch.object(search, "graph_search", return_value={}),
            patch.object(search.reranker, "is_reranker_available", lambda: False),
        ):
            out = search.hybrid_search("q", top_k=5)
        self.assertEqual(out["query_metadata"]["confidence"], "unknown")
        self.assertEqual([r["knowledge_id"] for r in out["results"]], ["A"])
        self.assertIsNone(out["results"][0]["relevance"])


class TestCompressionPreservesConfidence(unittest.TestCase):
    def test_confidence_survives_compression(self) -> None:
        from backend.llm.token_optimizer import compress_knowledge_context

        answer = {"type": "knowledge", "results": [{"text": "t"}], "total": 1, "confidence": "low"}
        out = compress_knowledge_context(answer)
        self.assertEqual(out["confidence"], "low")

    def test_absent_confidence_not_invented(self) -> None:
        from backend.llm.token_optimizer import compress_knowledge_context

        answer = {"type": "knowledge", "results": [{"text": "t"}], "total": 1}
        out = compress_knowledge_context(answer)
        self.assertNotIn("confidence", out)


class TestFormatNodeConfidence(unittest.TestCase):
    def test_confidence_surfaced_into_knowledge_answer(self) -> None:
        from backend.orchestrator.nodes import format_node

        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = False
            state = {
                "query": "什么是 standard deduction",
                "intent": "knowledge",
                "confidence": "keyword_match",
                "kb_results": {
                    "results": [],
                    "total": 0,
                    "query_metadata": {"confidence": "low"},
                },
                "nodes_visited": [],
            }
            result = format_node(state)
            self.assertEqual(result["response"]["answer"]["confidence"], "low")
        finally:
            cfg.ENABLE_LLM = original


if __name__ == "__main__":
    unittest.main()
