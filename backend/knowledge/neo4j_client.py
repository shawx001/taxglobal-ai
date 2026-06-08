"""Neo4j driver singleton and query helper."""

from __future__ import annotations

import logging
from typing import Any

from backend import config

logger = logging.getLogger("taxglobal.neo4j")

_driver: Any | None = None

_SCHEMA_STATEMENTS = (
    "CREATE CONSTRAINT tax_rule_id IF NOT EXISTS FOR (n:TaxRule) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT jurisdiction_code IF NOT EXISTS FOR (n:Jurisdiction) REQUIRE n.code IS UNIQUE",
    "CREATE CONSTRAINT source_id IF NOT EXISTS FOR (n:Source) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (n:Topic) REQUIRE n.id IS UNIQUE",
)


def init_neo4j() -> None:
    """Initialize the Neo4j driver. Safe to call at app startup."""

    global _driver
    if _driver is not None:
        return  # already initialized; call close_neo4j() first to reinitialize
    driver: Any | None = None
    if not config.ENABLE_NEO4J:
        logger.warning("Neo4j disabled via ENABLE_NEO4J=false")
        return
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
            connection_timeout=5,
        )
        driver.verify_connectivity()
        with driver.session() as session:
            for statement in _SCHEMA_STATEMENTS:
                session.run(statement).consume()
        _driver = driver
        logger.info("Neo4j connected")
    except Exception:
        logger.exception("Neo4j connection failed; degrading gracefully")
        if driver is not None:
            driver.close()
        _driver = None


def close_neo4j() -> None:
    """Close the Neo4j driver. Safe to call at app shutdown."""

    global _driver
    if _driver is not None:
        _driver.close()
    _driver = None
    logger.info("Neo4j disconnected")


def get_driver() -> Any | None:
    """Return the Neo4j driver instance, or None if unavailable."""

    return _driver


def run_query(cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute a Cypher query and return record dictionaries."""

    if _driver is None:
        raise RuntimeError("Neo4j is not available")
    with _driver.session() as session:
        result = session.run(cypher, params or {})
        return [record.data() for record in result]


def is_neo4j_available() -> bool:
    """Return whether Neo4j initialized successfully."""

    return _driver is not None
