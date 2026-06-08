"""Chroma vector store management."""

from __future__ import annotations

import logging
from typing import Any

from backend import config

logger = logging.getLogger("taxglobal.chroma")

_client: Any | None = None
_collection: Any | None = None


def init_chroma() -> None:
    """Initialize Chroma persistent client and collection."""

    global _client, _collection
    if not config.ENABLE_CHROMA:
        logger.warning("Chroma disabled via ENABLE_CHROMA=false")
        return
    try:
        import chromadb

        client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        collection = client.get_or_create_collection(
            name=config.CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        _client = client
        _collection = collection
        logger.info("Chroma initialized: collection=%s", config.CHROMA_COLLECTION)
    except Exception:
        logger.exception("Chroma init failed; degrading gracefully")
        _client = None
        _collection = None


def close_chroma() -> None:
    """Clear Chroma references. PersistentClient auto-persists."""

    global _client, _collection
    _client = None
    _collection = None
    logger.info("Chroma closed")


def get_collection() -> Any | None:
    """Return the Chroma collection, or None if unavailable."""

    return _collection


def is_chroma_available() -> bool:
    """Return whether Chroma initialized successfully."""

    return _collection is not None
