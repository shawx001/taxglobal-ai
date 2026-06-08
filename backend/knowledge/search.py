"""Hybrid knowledge search: Chroma vectors + Neo4j graph traversal."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.knowledge import embedder, neo4j_client, vector_store

logger = logging.getLogger("taxglobal.knowledge.search")

DEFAULT_TOP_K = 5
MAX_TOP_K = 20


def _clamp_top_k(top_k: int) -> int:
    return max(1, min(MAX_TOP_K, top_k))


def _build_where(filters: dict[str, Any] | None) -> dict[str, Any] | None:
    if not filters:
        return None

    clauses: list[dict[str, Any]] = []
    for key, value in filters.items():
        if value is None:
            continue
        if key == "jurisdiction" and value != "US":
            clauses.append({"$or": [{"jurisdiction": value}, {"jurisdiction": "US"}]})
        else:
            clauses.append({key: value})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _first_row(result: dict[str, Any], key: str) -> list[Any]:
    values = result.get(key)
    if not values:
        return []
    first = values[0]
    return first if isinstance(first, list) else []


def vector_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Semantic similarity search via Chroma."""

    if not vector_store.is_chroma_available():
        logger.warning("Chroma unavailable; vector search skipped")
        return []
    if not embedder.is_embedder_available():
        logger.warning("Embedder unavailable; vector search skipped")
        return []

    collection = vector_store.get_collection()
    if collection is None:
        logger.warning("Chroma collection unavailable; vector search skipped")
        return []

    try:
        embedding = embedder.embed_text(query)
        result = collection.query(
            query_embeddings=[embedding],
            n_results=_clamp_top_k(top_k),
            where=_build_where(filters),
        )
    except Exception as exc:
        logger.warning("Vector search failed; degrading to empty results: %s", exc.__class__.__name__)
        return []

    ids = _first_row(result, "ids")
    documents = _first_row(result, "documents")
    distances = _first_row(result, "distances")
    metadatas = _first_row(result, "metadatas")

    hits: list[dict[str, Any]] = []
    for index, knowledge_id in enumerate(ids):
        distance = distances[index] if index < len(distances) and distances[index] is not None else 1
        hits.append(
            {
                "knowledge_id": knowledge_id,
                "content": documents[index] if index < len(documents) else "",
                "score": max(0.0, min(1.0, round(1 - float(distance), 6))),
                "metadata": metadatas[index] if index < len(metadatas) and metadatas[index] else {},
            }
        )
    return hits


def _node_value(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        return node.get(key)
    try:
        return node[key]
    except Exception:
        return getattr(node, key, None)


def _source_from_node(node: Any) -> dict[str, Any]:
    return {
        "source_id": _node_value(node, "id"),
        "title": _node_value(node, "title"),
        "url": _node_value(node, "url"),
        "publisher": _node_value(node, "publisher"),
    }


def graph_search(knowledge_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Expand knowledge_ids via Neo4j relationships in one batched query."""

    if not knowledge_ids:
        return {}
    if not neo4j_client.is_neo4j_available():
        logger.warning("Neo4j unavailable; graph expansion skipped")
        return {}

    cypher = """
    UNWIND $ids AS kid
    MATCH (r:TaxRule {id: kid})
    OPTIONAL MATCH (r)-[:APPLIES_TO]->(j:Jurisdiction)
    OPTIONAL MATCH (r)-[:ABOUT]->(t:Topic)
    OPTIONAL MATCH (r)-[:CITED_FROM]->(s:Source)
    RETURN r.id AS id,
           collect(DISTINCT j) AS jurisdictions,
           collect(DISTINCT t) AS topics,
           collect(DISTINCT s) AS sources
    """
    try:
        rows = neo4j_client.run_query(cypher, {"ids": knowledge_ids})
    except Exception as exc:
        logger.warning("Graph expansion failed; degrading to vector-only results: %s", exc.__class__.__name__)
        return {}
    expansions: dict[str, dict[str, Any]] = {}
    for row in rows:
        knowledge_id = row.get("id")
        if not knowledge_id:
            continue
        expansions[knowledge_id] = {
            "jurisdictions": [
                {
                    "code": _node_value(node, "code"),
                    "name": _node_value(node, "name"),
                    "type": _node_value(node, "type"),
                }
                for node in row.get("jurisdictions", [])
                if node
            ],
            "topics": [
                {
                    "id": _node_value(node, "id"),
                    "name": _node_value(node, "name"),
                }
                for node in row.get("topics", [])
                if node
            ],
            "sources": [
                source
                for source in (_source_from_node(node) for node in row.get("sources", []) if node)
                if source.get("source_id")
            ],
        }
    return expansions


def _split_content(document: str) -> tuple[str, str]:
    if ":" not in document:
        return "knowledge", document
    title, content = document.split(":", 1)
    return title.strip(), content.strip()


def _fallback_sources(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw_source_ids = metadata.get("source_ids", "[]")
    if isinstance(raw_source_ids, str):
        try:
            source_ids = json.loads(raw_source_ids)
        except json.JSONDecodeError:
            source_ids = []
    elif isinstance(raw_source_ids, list):
        source_ids = raw_source_ids
    else:
        source_ids = []
    return [{"source_id": source_id, "title": None, "url": None, "publisher": None} for source_id in source_ids]


def _retrieval_method(vector_hits: list[dict[str, Any]], graph_expansions: dict[str, dict[str, Any]]) -> str:
    if not vector_hits:
        return "none"
    if graph_expansions:
        return "hybrid"
    return "vector_only"


def hybrid_search(
    query: str,
    *,
    jurisdiction: str | None = None,
    topic: str | None = None,
    tax_year: int | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    """Orchestrate vector + graph search, merge, deduplicate, and rank."""

    clamped_top_k = _clamp_top_k(top_k)
    filters = {
        key: value
        for key, value in {
            "jurisdiction": jurisdiction,
            "topic": topic,
            "tax_year": tax_year,
        }.items()
        if value is not None
    }
    vector_hits = vector_search(query, top_k=clamped_top_k, filters=filters)
    if not vector_hits:
        return {
            "results": [],
            "total": 0,
            "query_metadata": {
                "vector_hits": 0,
                "graph_expansions": 0,
                "retrieval_method": "none",
            },
        }

    knowledge_ids = [hit["knowledge_id"] for hit in vector_hits]
    graph_expansions = graph_search(knowledge_ids)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for hit in sorted(vector_hits, key=lambda item: item["score"], reverse=True):
        knowledge_id = hit["knowledge_id"]
        if knowledge_id in seen:
            continue
        seen.add(knowledge_id)

        metadata = hit.get("metadata", {})
        graph_data = graph_expansions.get(knowledge_id, {})
        title, content = _split_content(str(hit.get("content", "")))
        graph_sources = [source for source in graph_data.get("sources", []) if source.get("source_id")]
        sources = graph_sources or _fallback_sources(metadata)
        if not sources:
            continue
        topics = [
            topic_node.get("name") or topic_node.get("id")
            for topic_node in graph_data.get("topics", [])
            if topic_node.get("name") or topic_node.get("id")
        ]
        if not topics and metadata.get("topic"):
            topics = [metadata["topic"]]
        related_jurisdictions = [
            jurisdiction_node.get("code")
            for jurisdiction_node in graph_data.get("jurisdictions", [])
            if jurisdiction_node.get("code")
        ]
        if not related_jurisdictions and metadata.get("jurisdiction"):
            related_jurisdictions = [metadata["jurisdiction"]]

        results.append(
            {
                "knowledge_id": knowledge_id,
                "title": title,
                "content": content,
                "jurisdiction": metadata.get("jurisdiction"),
                "topics": topics,
                "sources": sources,
                "related_jurisdictions": related_jurisdictions,
                "score": hit["score"],
                "tax_year": metadata.get("tax_year"),
            }
        )

    return {
        "results": results[:clamped_top_k],
        "total": len(results[:clamped_top_k]),
        "query_metadata": {
            "vector_hits": len(vector_hits),
            "graph_expansions": len(graph_expansions),
            "retrieval_method": _retrieval_method(vector_hits, graph_expansions),
        },
    }
