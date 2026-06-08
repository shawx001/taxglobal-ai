"""PostgreSQL connection pool and session management."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from backend import config

logger = logging.getLogger("taxglobal.db")

try:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.orm import DeclarativeBase

    class Base(DeclarativeBase):
        """SQLAlchemy declarative base for ORM models."""

except ModuleNotFoundError:
    text = None
    AsyncSession = Any  # type: ignore[misc, assignment]

    class Base:  # type: ignore[no-redef]
        """Fallback base used when SQLAlchemy is not installed locally."""

        metadata = None

    def create_async_engine(*args: Any, **kwargs: Any) -> Any:
        raise ModuleNotFoundError("sqlalchemy")

    def async_sessionmaker(*args: Any, **kwargs: Any) -> Any:
        raise ModuleNotFoundError("sqlalchemy")


_engine: Any | None = None
_session_factory: Any | None = None


async def init_db() -> None:
    """Create async engine and session factory. Safe to call at app startup."""

    global _engine, _session_factory
    engine: Any | None = None
    if not config.ENABLE_POSTGRES:
        logger.warning("PostgreSQL disabled via ENABLE_POSTGRES=false")
        return
    try:
        engine = create_async_engine(
            config.DATABASE_URL,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        if text is None:
            raise RuntimeError("SQLAlchemy is not available")
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        _engine = engine
        _session_factory = session_factory
        logger.info("PostgreSQL connected")
    except Exception:
        logger.exception("PostgreSQL connection failed; degrading gracefully")
        if engine is not None:
            await engine.dispose()
        _engine = None
        _session_factory = None


async def close_db() -> None:
    """Dispose the async engine. Safe to call at app shutdown."""

    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    logger.info("PostgreSQL disconnected")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session for FastAPI dependencies."""

    if _session_factory is None:
        raise RuntimeError("PostgreSQL is not available")
    async with _session_factory() as session:
        yield session


def is_pg_available() -> bool:
    """Return whether PostgreSQL initialized successfully."""

    return _engine is not None and _session_factory is not None
