"""Centralized backend configuration read from environment variables."""

from __future__ import annotations

import os


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool) -> bool:
    value = _env(key, "true" if default else "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


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

# === M3: LLM Provider ===
ENABLE_LLM: bool = _env_bool("ENABLE_LLM", False)
LLM_PROVIDER: str = _env("TAXGLOBAL_LLM_PROVIDER", "deepseek")
LLM_API_KEY: str = _env("TAXGLOBAL_LLM_API_KEY", "")
LLM_MODEL: str = _env("TAXGLOBAL_LLM_MODEL", "")
LLM_BASE_URL: str = _env("TAXGLOBAL_LLM_BASE_URL", "")
LLM_TIMEOUT: float = _env_float("TAXGLOBAL_LLM_TIMEOUT", 30.0)
LLM_FAILOVER_PROVIDER: str = _env("TAXGLOBAL_LLM_FAILOVER_PROVIDER", "openai")
LLM_FAILOVER_API_KEY: str = _env("TAXGLOBAL_LLM_FAILOVER_API_KEY", "")
LLM_FAILOVER_MODEL: str = _env("TAXGLOBAL_LLM_FAILOVER_MODEL", "gpt-4o-mini")

# === M3.6: Vision (W-2 OCR) ===
# Empty model = vision disabled. Uses the same provider credentials as the
# text LLM ("mock" provider enables the deterministic test extractor).
VISION_MODEL: str = _env("TAXGLOBAL_VISION_MODEL", "")

# === M3.7: LLM cost tracking (USD per 1M tokens, env-overridable) ===
LLM_PRICE_INPUT_MTOK: str = _env("TAXGLOBAL_LLM_PRICE_INPUT_MTOK", "0.14")
LLM_PRICE_OUTPUT_MTOK: str = _env("TAXGLOBAL_LLM_PRICE_OUTPUT_MTOK", "0.28")
