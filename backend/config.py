"""Centralized backend configuration read from environment variables."""

from __future__ import annotations

import os


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool) -> bool:
    value = _env(key, "true" if default else "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


DATABASE_URL: str = _env("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/taxglobal")
DATABASE_SYNC_URL: str = _env("DATABASE_SYNC_URL", "postgresql://postgres:postgres@localhost:5432/taxglobal")

NEO4J_URI: str = _env("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = _env("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = _env("NEO4J_PASSWORD", "taxglobal")

CHROMA_PERSIST_DIR: str = _env("CHROMA_PERSIST_DIR", "data/chroma")
CHROMA_COLLECTION: str = _env("CHROMA_COLLECTION", "tax_knowledge")

EMBEDDING_MODEL: str = _env("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DEVICE: str = _env("EMBEDDING_DEVICE", "cpu")

ENABLE_POSTGRES: bool = _env_bool("ENABLE_POSTGRES", True)
ENABLE_NEO4J: bool = _env_bool("ENABLE_NEO4J", True)
ENABLE_CHROMA: bool = _env_bool("ENABLE_CHROMA", True)
