"""Knowledge ingestion: versioned JSON -> Neo4j graph + Chroma vectors."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from backend.knowledge import embedder, neo4j_client, vector_store

logger = logging.getLogger("taxglobal.knowledge.ingestion")

REQUIRED_ITEM_FIELDS = ("knowledge_id", "topic", "jurisdiction", "summary", "source_ids")
DEFAULT_TAX_YEAR = 2026
BATCH_SIZE = 100


def jurisdiction_type(code: str) -> str:
    """Infer graph jurisdiction type from a knowledge jurisdiction code."""

    return "federal" if code == "US" else "state"


def _jurisdiction_name(code: str) -> str:
    return "United States" if code == "US" else code


def _source_lookup(sources: dict[str, dict[str, Any]] | list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if isinstance(sources, dict):
        return sources
    return {source["source_id"]: source for source in sources}


def validate_items(items: list[dict[str, Any]], sources: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Validate required knowledge item fields and source coverage."""

    errors: list[str] = []
    seen: set[str] = set()
    known_sources = set(sources or {})

    for index, item in enumerate(items):
        item_id = item.get("knowledge_id")
        label = item_id or f"item[{index}]"

        for field in REQUIRED_ITEM_FIELDS:
            if not item.get(field):
                errors.append(f"{label}: missing required field {field}")

        if item_id:
            if item_id in seen:
                errors.append(f"{item_id}: duplicate knowledge_id")
            seen.add(item_id)

        source_ids = item.get("source_ids")
        if source_ids and not isinstance(source_ids, list):
            errors.append(f"{label}: source_ids must be a list")
        elif sources is not None and source_ids:
            for source_id in source_ids:
                if source_id not in known_sources:
                    errors.append(f"{label}: source_id {source_id} is not present in source_manifest")

    return errors


def _tax_year(item: dict[str, Any]) -> int:
    effective_date = str(item.get("effective_date", ""))
    if len(effective_date) >= 4 and effective_date[:4].isdigit():
        return int(effective_date[:4])
    return int(item.get("tax_year", DEFAULT_TAX_YEAR))


def ingest_to_neo4j(items: list[dict[str, Any]], sources: dict[str, dict[str, Any]] | list[dict[str, Any]]) -> int:
    """Ingest items and source relationships into Neo4j with idempotent MERGE statements."""

    if not neo4j_client.is_neo4j_available():
        logger.warning("Neo4j unavailable; skipping graph ingestion")
        return 0

    source_map = _source_lookup(sources)
    for item in items:
        rule_params = {
            "id": item["knowledge_id"],
            "title": item.get("title") or item["topic"],
            "content": item["summary"],
            "tax_year": _tax_year(item),
            "rule_type": item["topic"],
            "status": item.get("status", "effective"),
            "effective_date": item.get("effective_date"),
        }
        neo4j_client.run_query(
            """
            MERGE (r:TaxRule {id: $id})
            SET r.title = $title,
                r.content = $content,
                r.tax_year = $tax_year,
                r.rule_type = $rule_type,
                r.status = $status,
                r.effective_date = $effective_date
            """,
            rule_params,
        )

        jurisdiction = item["jurisdiction"]
        neo4j_client.run_query(
            """
            MATCH (r:TaxRule {id: $id})
            MERGE (j:Jurisdiction {code: $jurisdiction})
            SET j.name = $jurisdiction_name,
                j.type = $jurisdiction_type
            MERGE (r)-[:APPLIES_TO]->(j)
            """,
            {
                "id": item["knowledge_id"],
                "jurisdiction": jurisdiction,
                "jurisdiction_name": _jurisdiction_name(jurisdiction),
                "jurisdiction_type": jurisdiction_type(jurisdiction),
            },
        )

        topic = item["topic"]
        neo4j_client.run_query(
            """
            MATCH (r:TaxRule {id: $id})
            MERGE (t:Topic {id: $topic})
            SET t.name = $topic
            MERGE (r)-[:ABOUT]->(t)
            """,
            {"id": item["knowledge_id"], "topic": topic},
        )

        for source_id in item["source_ids"]:
            source = source_map.get(source_id)
            if source is None:
                logger.warning(
                    "source_id %s not in manifest; skipping CITED_FROM for %s",
                    source_id,
                    item["knowledge_id"],
                )
                continue
            neo4j_client.run_query(
                """
                MATCH (r:TaxRule {id: $id})
                MERGE (s:Source {id: $source_id})
                SET s.title = $title,
                    s.url = $source_url,
                    s.publisher = $publisher,
                    s.jurisdiction = $source_jurisdiction
                MERGE (r)-[:CITED_FROM]->(s)
                """,
                {
                    "id": item["knowledge_id"],
                    "source_id": source_id,
                    "title": source.get("title", source_id),
                    "source_url": source.get("source_url"),
                    "publisher": source.get("publisher"),
                    "source_jurisdiction": source.get("jurisdiction"),
                },
            )

    return len(items)


def ingest_to_chroma(items: list[dict[str, Any]]) -> int:
    """Ingest items into Chroma with idempotent upsert batches."""

    if not vector_store.is_chroma_available():
        logger.warning("Chroma unavailable; skipping vector ingestion")
        return 0
    if not embedder.is_embedder_available():
        logger.warning("Embedder unavailable; skipping vector ingestion")
        return 0

    collection = vector_store.get_collection()
    if collection is None:
        logger.warning("Chroma collection unavailable; skipping vector ingestion")
        return 0

    count = 0
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start : start + BATCH_SIZE]
        documents = [f"{item['topic']}: {item['summary']}" for item in batch]
        embeddings = embedder.embed_batch(documents)
        collection.upsert(
            ids=[item["knowledge_id"] for item in batch],
            documents=documents,
            embeddings=embeddings,
            metadatas=[
                {
                    "jurisdiction": item["jurisdiction"],
                    "topic": item["topic"],
                    "tax_year": _tax_year(item),
                    "source_ids": json.dumps(item["source_ids"], separators=(",", ":")),
                    "status": item.get("status", "effective"),
                }
                for item in batch
            ],
        )
        count += len(batch)

    return count


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_items(knowledge_dir: Path) -> list[dict[str, Any]]:
    if not knowledge_dir.is_dir():
        raise ValueError(f"Knowledge directory does not exist: {knowledge_dir}")

    json_paths = sorted(knowledge_dir.glob("*.json"))
    if not json_paths:
        raise ValueError(f"Knowledge directory contains no JSON files: {knowledge_dir}")

    items: list[dict[str, Any]] = []
    for path in json_paths:
        data = _read_json(path)
        items.extend(data.get("items", []))
    if not items:
        raise ValueError(f"Knowledge directory contains no items: {knowledge_dir}")
    return items


def _load_sources(source_manifest_path: Path) -> dict[str, dict[str, Any]]:
    manifest = _read_json(source_manifest_path)
    return {source["source_id"]: source for source in manifest.get("sources", [])}


def ingest_all(knowledge_dir: str | Path, source_manifest_path: str | Path) -> dict[str, Any]:
    """Validate and ingest all knowledge JSON files from a directory."""

    knowledge_path = Path(knowledge_dir)
    manifest_path = Path(source_manifest_path)
    items = _load_items(knowledge_path)
    sources = _load_sources(manifest_path)
    errors = validate_items(items, sources=sources)
    if errors:
        raise ValueError("Knowledge validation failed: " + "; ".join(errors))

    neo4j_count = ingest_to_neo4j(items, sources)
    chroma_count = ingest_to_chroma(items)
    return {
        "neo4j_count": neo4j_count,
        "chroma_count": chroma_count,
        "total_items": len(items),
        "errors": [],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest TaxGlobal knowledge JSON into Neo4j and Chroma.")
    parser.add_argument("--tax-year", type=int, default=DEFAULT_TAX_YEAR)
    parser.add_argument("--knowledge-dir", type=Path)
    parser.add_argument("--source-manifest", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    knowledge_dir = args.knowledge_dir or Path("data") / "knowledge" / "us" / str(args.tax_year)
    source_manifest = (
        args.source_manifest or Path("data") / "sources" / "us" / str(args.tax_year) / "source_manifest.json"
    )
    neo4j_client.init_neo4j()
    vector_store.init_chroma()
    embedder.init_embedder()
    try:
        stats = ingest_all(knowledge_dir, source_manifest)
        print(json.dumps(stats, indent=2, sort_keys=True))
    finally:
        embedder.close_embedder()
        vector_store.close_chroma()
        neo4j_client.close_neo4j()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
