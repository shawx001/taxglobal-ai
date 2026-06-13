"""Local cross-encoder reranker (Phase C.1).

Bi-encoder vector recall is fast but coarse; a cross-encoder scores each
(query, passage) pair jointly for far better top-k precision. Mirrors
embedder.py exactly: lazy local-only load, graceful degradation, same
on/off contract. When the model is absent (e.g. CI), is_reranker_available()
is False and callers fall back to the vector ordering unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from backend import config

logger = logging.getLogger("taxglobal.reranker")

_model: Any | None = None


def init_reranker() -> None:
    """Load the local cross-encoder once."""

    global _model
    if _model is not None:
        return  # already initialized; call close_reranker() first to reinitialize
    if not config.ENABLE_RERANK:
        logger.warning("Reranker disabled via ENABLE_RERANK=false")
        return
    if not config.ENABLE_CHROMA:
        # Reranking reorders vector-retrieval results; with Chroma off there is
        # nothing to rerank, so skip loading the large model (calc-only/store-
        # disabled deployments).
        logger.info("Reranker skipped: vector retrieval disabled (ENABLE_CHROMA=false)")
        return
    try:
        import os

        from sentence_transformers import CrossEncoder

        # Force local-only loading: never download from Hugging Face at runtime.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        _model = CrossEncoder(
            config.RERANK_MODEL,
            device=config.EMBEDDING_DEVICE,
            local_files_only=True,
        )
        logger.info("Reranker model loaded: %s", config.RERANK_MODEL)
    except Exception:
        logger.exception("Reranker model load failed; degrading gracefully")
        _model = None


def close_reranker() -> None:
    """Release the reranker reference for reloads/tests in the same process."""

    global _model
    _model = None
    logger.info("Reranker model released")


def is_reranker_available() -> bool:
    """Return whether the cross-encoder loaded successfully."""

    return _model is not None


def rerank_scores(query: str, passages: list[str]) -> list[float]:
    """Return one relevance score per passage (higher = more relevant).

    Raises RuntimeError when the model is unavailable so callers fall back
    to the existing vector order.
    """

    if _model is None:
        raise RuntimeError("Reranker model is not available")
    if not passages:
        return []
    pairs = [(query, passage) for passage in passages]
    scores = _model.predict(pairs)
    return [float(score) for score in scores]
