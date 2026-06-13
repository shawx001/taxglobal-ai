"""Corrective RAG relevance grading (Phase C.2).

The cross-encoder rerank score is a relevance signal, so CRAG reuses it
(no extra model): grade the reranked candidate set, drop clearly
irrelevant chunks, and label overall retrieval confidence so the response
layer can fall back honestly ("the KB has nothing on this") instead of
dressing up the least-irrelevant noise.

SAFETY: grading + dropping only happen when results were actually reranked
(a strong relevance signal). Without reranking the vector cosine is too
weak to gate on, so confidence is "unknown" and nothing is dropped —
behavior is identical to pre-C.2 (and to a deployment whose reranker
model is not yet cached).
"""

from __future__ import annotations

import math
from typing import Any

from backend import config

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_UNKNOWN = "unknown"


def _sigmoid(value: float) -> float:
    # Numerically stable; bge-reranker emits raw logits, sigmoid → [0,1].
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _relevance(hit: dict[str, Any]) -> float:
    score = hit.get("rerank_score")
    if score is None:
        return 0.0
    return _sigmoid(float(score))


def grade_hits(hits: list[dict[str, Any]], reranked: bool) -> tuple[str, list[dict[str, Any]]]:
    """Return (confidence, kept_hits).

    - reranked + enabled: keep hits with sigmoid(rerank_score) >= AMBIGUOUS,
      annotate each kept hit with ``relevance``; confidence from the top hit
      (high >= RELEVANT, medium >= AMBIGUOUS, else low). A low batch keeps
      nothing → empty results signal "nothing relevant in KB".
    - otherwise: confidence "unknown", hits unchanged (no dropping).
    """

    if not config.ENABLE_CRAG or not reranked or not hits:
        return CONFIDENCE_UNKNOWN, hits

    relevant = config.CRAG_RELEVANT
    ambiguous = config.CRAG_AMBIGUOUS

    top_relevance = _relevance(hits[0])
    if top_relevance >= relevant:
        confidence = CONFIDENCE_HIGH
    elif top_relevance >= ambiguous:
        confidence = CONFIDENCE_MEDIUM
    else:
        confidence = CONFIDENCE_LOW

    kept: list[dict[str, Any]] = []
    for hit in hits:
        relevance = _relevance(hit)
        if relevance >= ambiguous:
            hit["relevance"] = round(relevance, 6)
            kept.append(hit)
    # Keep the label consistent with what survives: if nothing cleared the
    # bar (incl. a misconfig where ambiguous > relevant), it is low.
    if not kept:
        confidence = CONFIDENCE_LOW
    return confidence, kept
