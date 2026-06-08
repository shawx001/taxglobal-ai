# Codex Prompt: M2.1 三库基础设施（PostgreSQL + Neo4j + Chroma + Embedding）

> 先读：`/AGENTS.md`（铁律）→ `/ARCHITECTURE.md` → `docs/m2_step_plan.md` M2.1 节

## 任务

搭建 M2 的三套存储基础设施 + 本地 embedding 模型加载。**不改任何现有 API 逻辑**——只新增基础设施代码和连接管理。

## 核心约束

1. **向后兼容**：任何存储不可用时，`/calc/*` 和 `/api/states` 必须照常工作（graceful degradation）
2. **数据不出境**：embedding 用本地 sentence-transformers，不调任何外部 API
3. **现有测试不受影响**：`python -m unittest discover -s tests` 现有测试全绿

---

## 1. 新增依赖

### 文件：`backend/requirements.txt`

在现有依赖后追加（不修改已有行）：

```
# === M2: 三库基础设施 ===
# PostgreSQL
sqlalchemy[asyncio]>=2.0,<3.0
alembic>=1.13,<2.0
asyncpg>=0.30,<1.0

# Neo4j
neo4j>=5.0,<6.0

# Chroma (向量库)
chromadb>=0.4,<1.0

# Embedding (本地推理)
sentence-transformers>=2.2,<4.0

# LangChain (M2.5 开始用，依赖先装)
langchain-core>=0.2,<1.0
langchain-community>=0.2,<1.0
langgraph>=0.1,<1.0
```

### 文件：`backend/requirements-dev.txt`

追加：

```
# M2 test utilities
testcontainers>=4.0,<5.0
```

---

## 2. 配置管理

### 新增文件：`backend/config.py`

```python
"""Centralized configuration — reads from environment variables with sensible defaults."""

from __future__ import annotations

import os


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# --- PostgreSQL ---
DATABASE_URL: str = _env("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/taxglobal")
DATABASE_SYNC_URL: str = _env("DATABASE_SYNC_URL", "postgresql://postgres:postgres@localhost:5432/taxglobal")

# --- Neo4j ---
NEO4J_URI: str = _env("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = _env("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = _env("NEO4J_PASSWORD", "taxglobal")

# --- Chroma ---
CHROMA_PERSIST_DIR: str = _env("CHROMA_PERSIST_DIR", "data/chroma")
CHROMA_COLLECTION: str = _env("CHROMA_COLLECTION", "tax_knowledge")

# --- Embedding ---
EMBEDDING_MODEL: str = _env("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DEVICE: str = _env("EMBEDDING_DEVICE", "cpu")

# --- Feature flags (graceful degradation) ---
ENABLE_POSTGRES: bool = _env("ENABLE_POSTGRES", "true").lower() == "true"
ENABLE_NEO4J: bool = _env("ENABLE_NEO4J", "true").lower() == "true"
ENABLE_CHROMA: bool = _env("ENABLE_CHROMA", "true").lower() == "true"
```

---

## 3. PostgreSQL + SQLAlchemy + Alembic

### 新增文件：`backend/database.py`

```python
"""PostgreSQL connection pool and session management."""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend import config

logger = logging.getLogger("taxglobal.db")


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""
    pass


_engine = None
_session_factory = None


async def init_db() -> None:
    """Create async engine and session factory. Call once at app startup."""
    global _engine, _session_factory
    if not config.ENABLE_POSTGRES:
        logger.warning("PostgreSQL disabled via ENABLE_POSTGRES=false")
        return
    try:
        _engine = create_async_engine(
            config.DATABASE_URL,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        # Verify connectivity
        async with _engine.begin() as conn:
            await conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        logger.info("PostgreSQL connected")
    except Exception:
        logger.exception("PostgreSQL connection failed — degrading gracefully")
        _engine = None
        _session_factory = None


async def close_db() -> None:
    """Dispose engine. Call at app shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("PostgreSQL disconnected")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session, auto-closes after request."""
    if _session_factory is None:
        raise RuntimeError("PostgreSQL is not available")
    async with _session_factory() as session:
        yield session


def is_pg_available() -> bool:
    """Check if PostgreSQL is initialized and available."""
    return _engine is not None and _session_factory is not None
```

### 新增目录：`alembic/`

初始化 Alembic（Codex 须执行）：

```bash
cd <repo-root>
python -m alembic init alembic
```

然后编辑 `alembic/env.py`：
- 设置 `target_metadata = Base.metadata`
- 从 `backend.config` 读取 `DATABASE_SYNC_URL` 作为 sqlalchemy.url

### 新增迁移：`alembic/versions/001_initial_tables.py`

创建初始迁移（`alembic revision --autogenerate -m "initial tables"` 或手写）：

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    tax_year INT NOT NULL DEFAULT 2026,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, tax_year)
);

CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL,
    user_id UUID,
    action VARCHAR(50) NOT NULL,
    input JSONB,
    output JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_request ON audit_log(request_id);
CREATE INDEX idx_audit_user ON audit_log(user_id);
```

### 新增 ORM models：`backend/models.py`

定义 `User`、`Profile`、`AuditLog` 三个 SQLAlchemy ORM model，对应上述三张表。字段/类型/约束与 SQL 一致。

---

## 4. Neo4j 连接管理

### 新增文件：`backend/knowledge/__init__.py`

空文件（包标记）。

### 新增文件：`backend/knowledge/neo4j_client.py`

```python
"""Neo4j driver singleton and query helper."""

from __future__ import annotations

import logging

from backend import config

logger = logging.getLogger("taxglobal.neo4j")

_driver = None


def init_neo4j() -> None:
    """Initialize Neo4j driver. Call once at app startup."""
    global _driver
    if not config.ENABLE_NEO4J:
        logger.warning("Neo4j disabled via ENABLE_NEO4J=false")
        return
    try:
        from neo4j import GraphDatabase
        _driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
        )
        # Verify connectivity
        _driver.verify_connectivity()
        logger.info("Neo4j connected")
    except Exception:
        logger.exception("Neo4j connection failed — degrading gracefully")
        _driver = None


def close_neo4j() -> None:
    """Close Neo4j driver. Call at app shutdown."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j disconnected")


def get_driver():
    """Return the Neo4j driver instance (or None if unavailable)."""
    return _driver


def run_query(cypher: str, params: dict | None = None) -> list[dict]:
    """Execute a read query and return list of record dicts."""
    if _driver is None:
        raise RuntimeError("Neo4j is not available")
    with _driver.session() as session:
        result = session.run(cypher, params or {})
        return [record.data() for record in result]


def is_neo4j_available() -> bool:
    return _driver is not None
```

---

## 5. Chroma + Embedding 模型

### 新增文件：`backend/knowledge/embedder.py`

```python
"""Local embedding model (sentence-transformers, CPU, no external API)."""

from __future__ import annotations

import logging

from backend import config

logger = logging.getLogger("taxglobal.embedder")

_model = None


def init_embedder() -> None:
    """Load the embedding model into memory. Call once at app startup."""
    global _model
    if not config.ENABLE_CHROMA:
        logger.warning("Chroma/Embedder disabled via ENABLE_CHROMA=false")
        return
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(config.EMBEDDING_MODEL, device=config.EMBEDDING_DEVICE)
        logger.info("Embedding model loaded: %s", config.EMBEDDING_MODEL)
    except Exception:
        logger.exception("Embedding model load failed — degrading gracefully")
        _model = None


def embed_text(text: str) -> list[float]:
    """Embed a single text string. Returns a list of floats (384-dim for bge-small)."""
    if _model is None:
        raise RuntimeError("Embedding model is not available")
    return _model.encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts."""
    if _model is None:
        raise RuntimeError("Embedding model is not available")
    return _model.encode(texts, normalize_embeddings=True).tolist()


def is_embedder_available() -> bool:
    return _model is not None
```

### 新增文件：`backend/knowledge/vector_store.py`

```python
"""Chroma vector store management."""

from __future__ import annotations

import logging

from backend import config

logger = logging.getLogger("taxglobal.chroma")

_client = None
_collection = None


def init_chroma() -> None:
    """Initialize Chroma persistent client. Call once at app startup."""
    global _client, _collection
    if not config.ENABLE_CHROMA:
        logger.warning("Chroma disabled via ENABLE_CHROMA=false")
        return
    try:
        import chromadb
        _client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        _collection = _client.get_or_create_collection(
            name=config.CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Chroma initialized: collection=%s, count=%d",
                     config.CHROMA_COLLECTION, _collection.count())
    except Exception:
        logger.exception("Chroma init failed — degrading gracefully")
        _client = None
        _collection = None


def close_chroma() -> None:
    """Cleanup (Chroma PersistentClient auto-persists, just clear refs)."""
    global _client, _collection
    _client = None
    _collection = None
    logger.info("Chroma closed")


def get_collection():
    """Return the Chroma collection (or None if unavailable)."""
    return _collection


def is_chroma_available() -> bool:
    return _collection is not None
```

---

## 6. 更新 `backend/main.py`

在 `create_app()` 中增加 startup/shutdown 生命周期事件来初始化/关闭三库 + embedding 模型。

**关键要求**：
- 使用 FastAPI `lifespan` context manager（不用已废弃的 `@app.on_event`）
- startup 时按顺序初始化：PostgreSQL → Neo4j → Chroma → Embedding
- 任何一个初始化失败 → 日志 warning，继续启动（graceful degradation）
- shutdown 时关闭所有连接
- **不改动任何现有路由/中间件/异常处理逻辑**

### 新增 `/api/health` 端点

```python
@app.get("/api/health")
def health_check() -> dict:
    """Return service health including each storage backend status."""
    from backend.database import is_pg_available
    from backend.knowledge.neo4j_client import is_neo4j_available
    from backend.knowledge.vector_store import is_chroma_available
    from backend.knowledge.embedder import is_embedder_available

    return {
        "status": "ok",
        "stores": {
            "postgresql": is_pg_available(),
            "neo4j": is_neo4j_available(),
            "chroma": is_chroma_available(),
            "embedder": is_embedder_available(),
        },
    }
```

---

## 7. 测试

### 新增文件：`tests/test_m2_infrastructure.py`

```python
"""M2.1 infrastructure tests — verify connections and graceful degradation."""

# test_pg_tables_defined:
#   - Import backend.models, verify User/Profile/AuditLog classes exist
#   - Check table names match expectations

# test_neo4j_client_module:
#   - Import backend.knowledge.neo4j_client
#   - Verify run_query raises RuntimeError when driver is None

# test_chroma_module:
#   - Import backend.knowledge.vector_store
#   - Verify get_collection returns None before init

# test_embedder_module:
#   - Import backend.knowledge.embedder
#   - Verify embed_text raises RuntimeError when model not loaded

# test_config_defaults:
#   - Import backend.config
#   - Verify DATABASE_URL, NEO4J_URI, CHROMA_PERSIST_DIR have sensible defaults

# test_health_endpoint:
#   - Use TestClient(app) to GET /api/health
#   - Without any DB running, all stores should be false but status is "ok"

# test_calc_api_still_works:
#   - Use TestClient(app) to call an existing /calc/* endpoint
#   - Verify it returns correct result even with all stores disabled
#   - Set ENABLE_POSTGRES=false, ENABLE_NEO4J=false, ENABLE_CHROMA=false in env
```

**注意**：测试不依赖真实 PostgreSQL/Neo4j/Chroma 运行。测试的是模块定义、graceful degradation 和现有 API 不受影响。

---

## 验收门禁

```powershell
python -m unittest discover -s tests
python -m ruff check engine backend tests
git diff --check
# 根 index.html hash 不变
# /calc/* 现有 API 行为完全不变
# /api/health 端点可访问
```

## Commit 格式

```
feat(backend): add three-store infrastructure for M2

Set up PostgreSQL (SQLAlchemy + Alembic), Neo4j driver, Chroma vector
store, and local sentence-transformers embedding model. All stores
degrade gracefully — existing /calc/* API unaffected when stores are
unavailable. Add /api/health endpoint for store status.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
