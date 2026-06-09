"""Phase 2: ingest OpenAccountants markdown skills into GraphRAG JSON.

Usage:
    python scripts/ingest_openaccountants.py --generate
    python scripts/ingest_openaccountants.py --generate --stats
    python scripts/ingest_openaccountants.py --generate --ingest

The generated JSON is compatible with backend.knowledge.ingestion.ingest_all().
Actual Neo4j/Chroma ingestion is optional; JSON generation works offline.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal environments
    yaml = None

OA_ROOT = Path(".claude/skills/openaccountants")
OUTPUT_KNOWLEDGE = Path("data/knowledge/oa/2025/oa_knowledge.json")
OUTPUT_MANIFEST = Path("data/sources/oa/2025/source_manifest.json")
TAX_YEAR = 2025
EFFECTIVE_DATE = "2025-01-01"
KNOWLEDGE_VERSION = "oa-2025-openaccountants-v0.1"
MIN_CHUNK_LENGTH = 50
SOURCE_URL = "https://github.com/openaccountants/openaccountants"

IRC_PATTERNS = (
    r"(?:IRC|26 USC)\s*(?:\u00a7|\u00c2\u00a7|sec\.?|section)?\s*[\d]+[A-Za-z]?(?:\([a-z0-9]+\))*",
    r"Treas\.?\s*Reg\.?\s*(?:\u00a7|\u00c2\u00a7|sec\.?|section)?\s*[\d]+\.[\d]+[A-Za-z]?\-[\d]+",
    r"(?:Rev\.?\s*Proc\.?|Rev\.?\s*Rul\.?)\s*[\d]{4}\-[\d]+",
    r"P\.?L\.?\s*[\d]+\-[\d]+",
)


def _safe_load_frontmatter(frontmatter: str) -> dict[str, Any]:
    if yaml is not None:
        try:
            parsed = yaml.safe_load(frontmatter) or {}
            if not isinstance(parsed, dict):
                return {}
            return parsed
        except Exception:
            pass

    parsed: dict[str, Any] = {}
    for raw_line in frontmatter.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        if value.startswith("[") and value.endswith("]"):
            parsed[key.strip()] = [
                item.strip().strip('"').strip("'")
                for item in value[1:-1].split(",")
                if item.strip()
            ]
        else:
            parsed[key.strip()] = value
    return parsed


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and return metadata plus remaining markdown."""

    match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, flags=re.DOTALL)
    if not match:
        return {}, text
    metadata = _safe_load_frontmatter(match.group(1))
    return metadata, text[match.end() :]


def infer_category(file_path: Path) -> str:
    """Infer top-level OpenAccountants category from a relative path."""

    first_part = file_path.parts[0] if file_path.parts else ""
    if first_part in {"federal", "us-states", "foundation", "cross-border"}:
        return first_part
    return first_part or "unknown"


def map_jurisdiction(frontmatter: dict[str, Any], file_path: Path) -> str:
    """Map OA jurisdiction labels to TaxGlobal jurisdiction codes."""

    jurisdiction = str(frontmatter.get("jurisdiction", "")).strip()
    normalized = jurisdiction.upper()
    if normalized:
        if normalized in {"US", "USA", "US-FEDERAL", "FEDERAL"}:
            return "US"
        if normalized.startswith("US-") and len(normalized) >= 5:
            return normalized.removeprefix("US-")
        if normalized in {"GLOBAL", "INTL", "INTERNATIONAL", "CROSS-BORDER", "CROSS_BORDER"}:
            return "INTL"
        if normalized.startswith("EU"):
            return "EU"
        return normalized

    parts = file_path.parts
    category = infer_category(file_path)
    if category == "federal" or category == "foundation":
        return "US"
    if category == "cross-border":
        return "INTL"
    if category == "us-states" and len(parts) > 1:
        return parts[1].upper()
    return "US"


def _strip_primary_heading(markdown: str) -> tuple[str | None, str]:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
            remaining = "\n".join(lines[:index] + lines[index + 1 :])
            return title, remaining.lstrip()
    return None, markdown


def chunk_by_h2(markdown: str) -> list[dict[str, Any]]:
    """Split markdown into chunks on H2 heading boundaries."""

    pieces = re.split(r"^(## .+)$", markdown, flags=re.MULTILINE)
    chunks: list[dict[str, Any]] = []

    preamble = pieces[0].strip()
    if preamble:
        chunks.append({"section_index": 0, "heading": "", "content": preamble})

    section_index = 1
    for index in range(1, len(pieces), 2):
        heading = pieces[index].removeprefix("##").strip()
        content = pieces[index + 1].strip() if index + 1 < len(pieces) else ""
        chunks.append({"section_index": section_index, "heading": heading, "content": content})
        section_index += 1

    return chunks


def extract_citations(text: str) -> list[str]:
    """Extract unique IRC, Treasury regulation, revenue ruling, and public law citations."""

    citations: list[str] = []
    seen: set[str] = set()
    for pattern in IRC_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            citation = re.sub(r"\s+", " ", match.group(0)).strip(" .;,")
            key = citation.casefold()
            if key not in seen:
                seen.add(key)
                citations.append(citation)
    return citations


def _sanitize_identifier(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return sanitized or "unknown"


def source_id_for_path(rel_path: Path) -> str:
    """Build a stable source id from the relative path to avoid README collisions."""

    stem_path = rel_path.with_suffix("")
    return "oa_" + "_".join(_sanitize_identifier(part) for part in stem_path.parts)


def _metadata_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _source_title(frontmatter: dict[str, Any], stem: str, markdown_title: str | None) -> str:
    title = markdown_title or str(frontmatter.get("name") or stem)
    version = frontmatter.get("version")
    if version and f"v{version}" not in title:
        title = f"{title} v{version}"
    return f"OpenAccountants: {title}"


def topic_for_file(frontmatter: dict[str, Any], source_id: str) -> str:
    """Return the OA topic, keeping no-frontmatter files distinct."""

    if frontmatter.get("name"):
        return str(frontmatter["name"])
    return source_id.removeprefix("oa_").replace("_", "-")


def _build_item(
    *,
    chunk: dict[str, Any],
    category: str,
    content: str,
    frontmatter: dict[str, Any],
    heading: str,
    jurisdiction: str,
    rel_path: Path,
    source_id: str,
    topic: str,
    total_sections: int,
) -> dict[str, Any]:
    citations = extract_citations(f"{heading}\n\n{content}")
    section_index = int(chunk["section_index"])
    return {
        "knowledge_id": f"{source_id}_s{section_index:02d}",
        "topic": topic,
        "jurisdiction": jurisdiction,
        "effective_date": EFFECTIVE_DATE,
        "summary": f"{heading}\n\n{content}",
        "title": heading,
        "source": "openaccountants",
        "source_ids": [source_id],
        "status": "effective",
        "rule_type": "knowledge",
        "citations": citations,
        "oa_metadata": {
            "file_path": rel_path.as_posix(),
            "category": category,
            "version": str(frontmatter.get("version", "")),
            "depends_on": _metadata_list(frontmatter.get("depends_on")),
            "validation_status": str(frontmatter.get("validation_status", "")),
            "section_index": section_index,
            "total_sections": total_sections,
        },
    }


def build_knowledge_and_manifest(oa_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Walk OA markdown files and return knowledge JSON plus source manifest JSON."""

    if not oa_root.exists():
        raise FileNotFoundError(f"OpenAccountants root does not exist: {oa_root}")

    items: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    for md_path in sorted(oa_root.rglob("*.md")):
        rel_path = md_path.relative_to(oa_root)
        category = infer_category(rel_path)
        source_id = source_id_for_path(rel_path)
        stem = md_path.stem
        text = md_path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        markdown_title, body_without_title = _strip_primary_heading(body)
        jurisdiction = map_jurisdiction(frontmatter, rel_path)
        topic = topic_for_file(frontmatter, source_id)

        sources.append(
            {
                "source_id": source_id,
                "title": _source_title(frontmatter, stem, markdown_title),
                "source_url": SOURCE_URL,
                "source_type": "markdown",
                "publisher": "OpenAccountants",
                "tax_year": TAX_YEAR,
                "jurisdiction": jurisdiction,
                "topics": [topic],
                "status": "source_verified_raw_fetch_blocked",
            }
        )

        chunks = chunk_by_h2(body_without_title)
        total_sections = len(chunks)
        for chunk in chunks:
            content = str(chunk["content"]).strip()
            if len(content) < MIN_CHUNK_LENGTH:
                continue
            heading = str(chunk["heading"] or f"Preamble ({stem})")
            items.append(
                _build_item(
                    chunk=chunk,
                    category=category,
                    content=content,
                    frontmatter=frontmatter,
                    heading=heading,
                    jurisdiction=jurisdiction,
                    rel_path=rel_path,
                    source_id=source_id,
                    topic=topic,
                    total_sections=total_sections,
                )
            )

    return (
        {
            "schema_version": "0.1",
            "knowledge_version": KNOWLEDGE_VERSION,
            "tax_year": TAX_YEAR,
            "jurisdiction": "US",
            "effective_date": EFFECTIVE_DATE,
            "items": items,
        },
        {
            "schema_version": "0.1",
            "retrieved_at": EFFECTIVE_DATE,
            "sources": sources,
        },
    )


def _print_stats(knowledge_json: dict[str, Any], manifest_json: dict[str, Any]) -> None:
    items = knowledge_json["items"]
    sources = manifest_json["sources"]
    jurisdictions = sorted({item["jurisdiction"] for item in items})
    citation_count = sum(len(item.get("citations", [])) for item in items)
    print(f"Files processed: {len(sources)}")
    print(f"Chunks created:  {len(items)}")
    print(f"Jurisdictions:   {len(jurisdictions)}")
    print(f"Citations:       {citation_count}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest OpenAccountants skills into GraphRAG.")
    parser.add_argument("--generate", action="store_true", help="Parse markdown and write JSON files.")
    parser.add_argument("--ingest", action="store_true", help="Also ingest generated JSON into Neo4j and Chroma.")
    parser.add_argument("--stats", action="store_true", help="Print parsing statistics.")
    parser.add_argument("--oa-root", type=Path, default=OA_ROOT)
    parser.add_argument("--knowledge-output", type=Path, default=OUTPUT_KNOWLEDGE)
    parser.add_argument("--manifest-output", type=Path, default=OUTPUT_MANIFEST)
    args = parser.parse_args(argv)

    if not args.generate and not args.stats and not args.ingest:
        parser.error("Specify --generate, --stats, and/or --ingest")

    knowledge_json, manifest_json = build_knowledge_and_manifest(args.oa_root)
    _print_stats(knowledge_json, manifest_json)

    if args.generate or args.ingest:
        _write_json(args.knowledge_output, knowledge_json)
        _write_json(args.manifest_output, manifest_json)
        print(f"Written: {args.knowledge_output}")
        print(f"Written: {args.manifest_output}")

    if args.ingest:
        from backend.knowledge import embedder, neo4j_client, vector_store
        from backend.knowledge.ingestion import ingest_all

        neo4j_client.init_neo4j()
        vector_store.init_chroma()
        embedder.init_embedder()
        try:
            result = ingest_all(args.knowledge_output.parent, args.manifest_output)
            print(json.dumps(result, indent=2, sort_keys=True))
        finally:
            embedder.close_embedder()
            vector_store.close_chroma()
            neo4j_client.close_neo4j()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
