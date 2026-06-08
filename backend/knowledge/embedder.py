"""Local embedding model wrapper using sentence-transformers."""

from __future__ import annotations

import logging
from typing import Any

from backend import config

logger = logging.getLogger("taxglobal.embedder")

_model: Any | None = None


def init_embedder() -> None:
    """Load the local embedding model once."""

    global _model
    if not config.ENABLE_CHROMA:
        logger.warning("Chroma/Embedder disabled via ENABLE_CHROMA=false")
        return
    try:
        import os

        from sentence_transformers import SentenceTransformer

        # Force local-only loading: never download from Hugging Face Hub at runtime.
        # The model must be pre-cached (e.g. via `huggingface-cli download`).
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        _model = SentenceTransformer(
            config.EMBEDDING_MODEL,
            device=config.EMBEDDING_DEVICE,
            local_files_only=True,
        )
        logger.info("Embedding model loaded: %s", config.EMBEDDING_MODEL)
    except Exception:
        logger.exception("Embedding model load failed; degrading gracefully")
        _model = None


def close_embedder() -> None:
    """Release the embedding model reference for reloads/tests in the same process."""

    global _model
    _model = None
    logger.info("Embedding model released")


def embed_text(text: str) -> list[float]:
    """Embed a single text string."""

    if _model is None:
        raise RuntimeError("Embedding model is not available")
    return _model.encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of text strings."""

    if _model is None:
        raise RuntimeError("Embedding model is not available")
    return _model.encode(texts, normalize_embeddings=True).tolist()


def is_embedder_available() -> bool:
    """Return whether the embedding model loaded successfully."""

    return _model is not None
