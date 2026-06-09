# Codex Prompt: Phase 2 — OpenAccountants GraphRAG Ingestion

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `backend/knowledge/ingestion.py` → `backend/knowledge/vector_store.py` → `backend/knowledge/neo4j_client.py`

## Task

Write a standalone ingestion script that converts 215 OpenAccountants `.md` skill files into structured knowledge items, then feeds them through our existing `ingestion.py` pipeline into Neo4j + Chroma. The script parses YAML frontmatter, chunks each file by `##` heading boundaries, extracts IRC/regulation citations, and generates two JSON files (knowledge items + source manifest) compatible with `ingest_all()`.

**Why:** These 215 files contain authoritative, IRC-cited US tax rules covering federal + 51 states + cross-border. Ingesting them makes this knowledge searchable via our existing `GET /api/knowledge/search` hybrid search API, enabling all future Agent Skills to retrieve OA content at runtime.

## Core Constraints

1. **No changes to existing code** — reuse `backend/knowledge/ingestion.py` functions as-is. Only add new files.
2. **Data sovereignty** — embedding is local (`BAAI/bge-small-zh-v1.5`), no external API calls.
3. **Graceful degradation** — script generates JSON even if Neo4j/Chroma are offline. The JSON output is the primary artifact; actual DB ingestion is optional.
4. **Incremental/idempotent** — MERGE in Neo4j, upsert in Chroma. Re-running the script must be safe.
5. **Provenance** — every chunk must carry `source: "openaccountants"` so OA content is distinguishable from our hand-authored knowledge.

## Input: OA File Structure

**Location:** `.claude/skills/openaccountants/` with 4 subdirectories:
- `federal/` — 11 files (US federal tax skills)
- `us-states/` — 154 files (50 states + DC, organized by 2-letter code subdirs)
- `foundation/` — 17 files (workflow base patterns)
- `cross-border/` — 33 files (EU, international, multi-jurisdiction)

**File format (75% have YAML frontmatter):**
```markdown
---
name: us-qbi-deduction
description: Tier 2 content skill for computing the §199A ...
version: 0.2
jurisdiction: US-FEDERAL
category: federal
depends_on: [us-tax-workflow-base, us-schedule-c-and-se-computation]
validation_status: ai-drafted-q3
---

# US QBI Deduction Skill v0.2

## What this file is, and what it is not
...content...

## Section 1 — Scope statement
...content...

## Section 2 — Year-specific figures
...content...
```

**Files without frontmatter** (25%, mostly README.md): treat the first `# ` heading as the title, infer jurisdiction from directory path.

## Output: Two JSON Files

### File 1: `data/knowledge/oa/2025/oa_knowledge.json`

```json
{
  "schema_version": "0.1",
  "knowledge_version": "oa-2025-openaccountants-v0.1",
  "tax_year": 2025,
  "jurisdiction": "US",
  "effective_date": "2025-01-01",
  "items": [
    {
      "knowledge_id": "oa_federal_us_qbi_deduction_s01",
      "topic": "us-qbi-deduction",
      "jurisdiction": "US",
      "effective_date": "2025-01-01",
      "summary": "Section 1 — Scope statement\n\nThis skill covers, for tax year 2025:\n- QBI computation from Schedule C...",
      "title": "Section 1 — Scope statement",
      "source_ids": ["oa_federal_us_qbi_deduction"],
      "status": "effective",
      "rule_type": "knowledge",
      "oa_metadata": {
        "file_path": "federal/us-qbi-deduction.md",
        "category": "federal",
        "version": "0.2",
        "depends_on": ["us-tax-workflow-base", "us-schedule-c-and-se-computation"],
        "validation_status": "ai-drafted-q3",
        "section_index": 1,
        "total_sections": 12
      }
    }
  ]
}
```

**knowledge_id format:** `oa_{category}_{filename_stem}_s{section_index:02d}`
- Example: `oa_federal_us_qbi_deduction_s03` for 3rd `##` section of `federal/us-qbi-deduction.md`
- Section 0 (`s00`) = content before the first `##` heading (intro/preamble) — only include if non-trivial (>50 chars after stripping frontmatter and `# ` title)

**topic:** from frontmatter `name` field. If no frontmatter, derive from filename stem (e.g., `ca-income-tax.md` → `ca-income-tax`).

**jurisdiction mapping:**
- Frontmatter `jurisdiction` values like `US-FEDERAL` → `"US"`
- `US-CA` → `"CA"`, `US-NY` → `"NY"`, etc. (strip `US-` prefix for state codes)
- Directory-inferred: `us-states/ca/` → `"CA"`, `federal/` → `"US"`, `cross-border/` → `"INTL"`, `foundation/` → `"US"`
- If frontmatter has `jurisdiction`, use it (mapped). Otherwise infer from directory.

### File 2: `data/sources/oa/2025/source_manifest.json`

```json
{
  "schema_version": "0.1",
  "retrieved_at": "2025-01-01",
  "sources": [
    {
      "source_id": "oa_federal_us_qbi_deduction",
      "title": "OpenAccountants: US QBI Deduction Skill v0.2",
      "source_url": "https://github.com/openaccountants/openaccountants",
      "source_type": "markdown",
      "publisher": "OpenAccountants",
      "tax_year": 2025,
      "jurisdiction": "US",
      "topics": ["us-qbi-deduction"],
      "status": "source_verified_raw_fetch_blocked"
    }
  ]
}
```

One source entry per .md file (not per chunk). **source_id format:** `oa_{category}_{filename_stem}`.

## Script: `scripts/ingest_openaccountants.py`

### Module structure (single file, ~300-400 lines):

```python
"""
Phase 2: Ingest 215 OpenAccountants .md skill files into GraphRAG.

Usage:
    python scripts/ingest_openaccountants.py --generate
    python scripts/ingest_openaccountants.py --generate --ingest

--generate  : Parse .md files, produce JSON output files
--ingest    : Also run ingestion into Neo4j + Chroma (requires services running)
"""
```

### Key functions:

```python
import re
import json
import yaml
import argparse
from pathlib import Path
from typing import Any

# --- Constants ---
OA_ROOT = Path(".claude/skills/openaccountants")
OUTPUT_KNOWLEDGE = Path("data/knowledge/oa/2025/oa_knowledge.json")
OUTPUT_MANIFEST = Path("data/sources/oa/2025/source_manifest.json")
TAX_YEAR = 2025
MIN_CHUNK_LENGTH = 50  # chars — skip trivially short sections

# --- Frontmatter parsing ---
def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and return (metadata_dict, remaining_markdown).
    If no frontmatter, return ({}, full_text)."""
    # Match --- ... --- at the start of the file
    # Use yaml.safe_load for the frontmatter block
    ...

# --- Jurisdiction mapping ---
def map_jurisdiction(frontmatter: dict, file_path: Path) -> str:
    """Map OA jurisdiction to our format.
    US-FEDERAL -> 'US', US-CA -> 'CA', GLOBAL -> 'INTL', etc.
    Fallback: infer from directory path."""
    ...

def infer_category(file_path: Path) -> str:
    """Infer category from directory: federal, us-states, foundation, cross-border."""
    # file_path is relative to OA_ROOT
    ...

# --- Markdown chunking ---
def chunk_by_h2(markdown: str) -> list[dict[str, str]]:
    """Split markdown on ## headings. Returns list of {heading, content}.
    Section 0 = content before first ##. Skip sections shorter than MIN_CHUNK_LENGTH."""
    # Use re.split(r'^(## .+)$', markdown, flags=re.MULTILINE)
    ...

# --- IRC citation extraction ---
# Regex patterns for IRC/regulation references found in OA files:
IRC_PATTERNS = [
    r'(?:IRC|26 USC)\s*[§§]?\s*[\d]+[A-Za-z]?(?:\([a-z0-9]+\))*',  # IRC §199A(a)(1)
    r'Treas\.?\s*Reg\.?\s*[§§]?\s*[\d]+\.[\d]+[A-Za-z]?\-[\d]+',     # Treas. Reg. §1.199A-5
    r'(?:Rev\.?\s*Proc\.?|Rev\.?\s*Rul\.?)\s*[\d]{4}\-[\d]+',          # Rev. Proc. 2024-40
    r'P\.?L\.?\s*[\d]+\-[\d]+',                                         # P.L. 119-21
]

def extract_citations(text: str) -> list[str]:
    """Extract unique IRC/regulation citations from text."""
    ...

# --- Main builder ---
def build_knowledge_and_manifest(oa_root: Path) -> tuple[dict, dict]:
    """Walk all .md files, parse, chunk, and return (knowledge_json, manifest_json)."""
    items = []
    sources = []

    for md_path in sorted(oa_root.rglob("*.md")):
        rel_path = md_path.relative_to(oa_root)
        category = infer_category(rel_path)
        stem = md_path.stem  # e.g., 'us-qbi-deduction'
        source_id = f"oa_{category}_{stem}".replace("-", "_")

        text = md_path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        jurisdiction = map_jurisdiction(frontmatter, rel_path)
        topic = frontmatter.get("name") or stem

        # Build source entry (one per file)
        sources.append({
            "source_id": source_id,
            "title": f"OpenAccountants: {frontmatter.get('name', stem)} v{frontmatter.get('version', '?')}",
            "source_url": "https://github.com/openaccountants/openaccountants",
            "source_type": "markdown",
            "publisher": "OpenAccountants",
            "tax_year": TAX_YEAR,
            "jurisdiction": jurisdiction,
            "topics": [topic],
            "status": "source_verified_raw_fetch_blocked",
        })

        # Chunk by ## heading
        chunks = chunk_by_h2(body)
        for idx, chunk in enumerate(chunks):
            knowledge_id = f"{source_id}_s{idx:02d}"
            heading = chunk["heading"] or f"Preamble ({stem})"
            content = chunk["content"].strip()

            if len(content) < MIN_CHUNK_LENGTH:
                continue

            items.append({
                "knowledge_id": knowledge_id,
                "topic": topic,
                "jurisdiction": jurisdiction,
                "effective_date": "2025-01-01",
                "summary": f"{heading}\n\n{content}",
                "title": heading,
                "source_ids": [source_id],
                "status": "effective",
                "rule_type": "knowledge",
            })

    knowledge_json = {
        "schema_version": "0.1",
        "knowledge_version": "oa-2025-openaccountants-v0.1",
        "tax_year": TAX_YEAR,
        "jurisdiction": "US",
        "effective_date": "2025-01-01",
        "items": items,
    }
    manifest_json = {
        "schema_version": "0.1",
        "retrieved_at": "2025-01-01",
        "sources": sources,
    }
    return knowledge_json, manifest_json


def main():
    parser = argparse.ArgumentParser(description="Ingest OpenAccountants skills into GraphRAG")
    parser.add_argument("--generate", action="store_true", help="Parse .md and write JSON files")
    parser.add_argument("--ingest", action="store_true", help="Also run DB ingestion (Neo4j+Chroma)")
    parser.add_argument("--oa-root", type=Path, default=OA_ROOT)
    parser.add_argument("--stats", action="store_true", help="Print stats only, don't write files")
    args = parser.parse_args()

    if not args.generate and not args.stats:
        parser.error("Specify --generate and/or --stats")

    knowledge_json, manifest_json = build_knowledge_and_manifest(args.oa_root)
    items = knowledge_json["items"]
    sources = manifest_json["sources"]

    # Print stats
    print(f"Files processed: {len(sources)}")
    print(f"Chunks created:  {len(items)}")
    print(f"Jurisdictions:   {len(set(i['jurisdiction'] for i in items))}")
    # ...additional stats...

    if args.generate:
        # Create output directories, write JSON files
        OUTPUT_KNOWLEDGE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_KNOWLEDGE.write_text(json.dumps(knowledge_json, indent=2, ensure_ascii=False), encoding="utf-8")
        OUTPUT_MANIFEST.write_text(json.dumps(manifest_json, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Written: {OUTPUT_KNOWLEDGE}")
        print(f"Written: {OUTPUT_MANIFEST}")

    if args.ingest:
        from backend.knowledge.ingestion import ingest_all
        from backend.knowledge import neo4j_client, vector_store, embedder
        neo4j_client.init_neo4j()
        vector_store.init_chroma()
        embedder.init_embedder()
        try:
            result = ingest_all(str(OUTPUT_KNOWLEDGE.parent), str(OUTPUT_MANIFEST))
            print(json.dumps(result, indent=2))
        finally:
            embedder.close_embedder()
            vector_store.close_chroma()
            neo4j_client.close_neo4j()
```

### Important implementation details:

1. **`parse_frontmatter`**: Use `yaml.safe_load()`. Handle files that start with `---\n` (has frontmatter) vs those that don't. Strip the frontmatter from the body before chunking.

2. **`chunk_by_h2`**: Split on lines matching `^## ` (not `###`). Each chunk gets the `##` heading as its `heading` field and all content until the next `## ` or EOF as `content`. The content BEFORE the first `## ` is section 0 (preamble).

3. **`map_jurisdiction`**: Priority order:
   - Frontmatter `jurisdiction` if present → map (`US-FEDERAL` → `US`, `US-XX` → `XX`, `GLOBAL` → `INTL`, `EU-27` → `EU`, `cross-border` → `INTL`)
   - Directory path → `federal/` → `US`, `us-states/xx/` → uppercase `XX`, `foundation/` → `US`, `cross-border/` → `INTL`

4. **`source_id` sanitization**: Replace `-` with `_` in the stem. Example: `us-qbi-deduction` → `oa_federal_us_qbi_deduction`. Must be unique per file.

5. **`knowledge_id` uniqueness**: `{source_id}_s{index:02d}` guarantees uniqueness since source_id is unique per file and index is unique per chunk within file.

6. **No `yaml` import issue**: `yaml` is from PyYAML. If not installed, add `PyYAML>=6.0,<7.0` to `requirements.txt`. Check first — it may already be a dependency.

## Tests: `tests/test_oa_ingestion.py`

```python
"""Tests for OpenAccountants GraphRAG ingestion script."""

import unittest
from pathlib import Path

# Import the script's functions
# The script is at scripts/ingest_openaccountants.py
# Either add scripts/ to path or restructure as a module

class TestFrontmatterParsing(unittest.TestCase):

    def test_parse_with_frontmatter(self):
        text = "---\nname: test-skill\nversion: 0.1\n---\n\n# Title\n\nContent"
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta["name"], "test-skill")
        self.assertIn("# Title", body)
        self.assertNotIn("---", body)

    def test_parse_without_frontmatter(self):
        text = "# Just a title\n\nSome content here"
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

class TestChunking(unittest.TestCase):

    def test_basic_h2_split(self):
        md = "Preamble text\n\n## Section 1\n\nContent 1\n\n## Section 2\n\nContent 2"
        chunks = chunk_by_h2(md)
        self.assertEqual(len(chunks), 3)  # preamble + 2 sections
        self.assertEqual(chunks[1]["heading"], "Section 1")
        self.assertIn("Content 1", chunks[1]["content"])

    def test_h3_not_split(self):
        md = "## Main\n\nText\n\n### Sub\n\nMore text"
        chunks = chunk_by_h2(md)
        self.assertEqual(len(chunks), 1)  # h3 should NOT cause a split
        self.assertIn("### Sub", chunks[0]["content"])

    def test_short_chunks_filtered(self):
        md = "## Short\n\nHi\n\n## Long enough section\n\n" + "x" * 100
        chunks = chunk_by_h2(md)
        # "Hi" is < MIN_CHUNK_LENGTH, should be filtered by caller
        # chunk_by_h2 returns all chunks; filtering is in build function

class TestJurisdictionMapping(unittest.TestCase):

    def test_us_federal(self):
        self.assertEqual(map_jurisdiction({"jurisdiction": "US-FEDERAL"}, Path("federal/x.md")), "US")

    def test_us_state(self):
        self.assertEqual(map_jurisdiction({"jurisdiction": "US-CA"}, Path("us-states/ca/x.md")), "CA")

    def test_directory_fallback(self):
        self.assertEqual(map_jurisdiction({}, Path("us-states/ny/x.md")), "NY")

    def test_cross_border(self):
        self.assertEqual(map_jurisdiction({"jurisdiction": "cross-border"}, Path("cross-border/x.md")), "INTL")

class TestCitationExtraction(unittest.TestCase):

    def test_irc_section(self):
        citations = extract_citations("See IRC §199A(a)(1) for details")
        self.assertTrue(any("199A" in c for c in citations))

    def test_treas_reg(self):
        citations = extract_citations("per Treas. Reg. §1.199A-5")
        self.assertTrue(any("1.199A-5" in c for c in citations))

    def test_public_law(self):
        citations = extract_citations("The One Big Beautiful Bill Act (P.L. 119-21)")
        self.assertTrue(any("119-21" in c for c in citations))

class TestEndToEnd(unittest.TestCase):
    """Integration test: parse actual OA files and validate output."""

    def test_full_build(self):
        oa_root = Path(".claude/skills/openaccountants")
        if not oa_root.exists():
            self.skipTest("OA skills not installed")

        knowledge, manifest = build_knowledge_and_manifest(oa_root)
        items = knowledge["items"]
        sources = manifest["sources"]

        # 215 files → 215 sources
        self.assertEqual(len(sources), 215)

        # Expect 500-1000 chunks (design spec says ~500-800)
        self.assertGreaterEqual(len(items), 400, "Too few chunks")
        self.assertLessEqual(len(items), 1500, "Too many chunks")

        # All knowledge_ids unique
        ids = [i["knowledge_id"] for i in items]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate knowledge_ids found")

        # All source_ids in manifest
        source_ids = {s["source_id"] for s in sources}
        for item in items:
            for sid in item["source_ids"]:
                self.assertIn(sid, source_ids, f"{sid} not in manifest")

        # Jurisdictions include US + at least CA, NY
        jurisdictions = {i["jurisdiction"] for i in items}
        self.assertIn("US", jurisdictions)
        self.assertIn("CA", jurisdictions)
        self.assertIn("NY", jurisdictions)

        # Required fields present
        for item in items[:20]:  # spot check first 20
            for field in ("knowledge_id", "topic", "jurisdiction", "summary", "source_ids"):
                self.assertIn(field, item, f"Missing {field}")
            self.assertIsInstance(item["source_ids"], list)
            self.assertGreater(len(item["summary"]), 0)

    def test_validates_with_existing_pipeline(self):
        """Generated items pass existing validate_items()."""
        oa_root = Path(".claude/skills/openaccountants")
        if not oa_root.exists():
            self.skipTest("OA skills not installed")

        knowledge, manifest = build_knowledge_and_manifest(oa_root)
        from backend.knowledge.ingestion import validate_items
        sources = {s["source_id"]: s for s in manifest["sources"]}
        errors = validate_items(knowledge["items"], sources=sources)
        self.assertEqual(errors, [], f"Validation errors: {errors[:5]}")
```

## Acceptance Gates

```powershell
# 1. Generate JSON (must work without Neo4j/Chroma)
python scripts/ingest_openaccountants.py --generate --stats

# 2. Verify output files exist and are valid JSON
python -c "import json; d=json.load(open('data/knowledge/oa/2025/oa_knowledge.json')); print(f'Items: {len(d[\"items\"])}')"
python -c "import json; d=json.load(open('data/sources/oa/2025/source_manifest.json')); print(f'Sources: {len(d[\"sources\"])}')"

# 3. Run tests
python -m unittest discover -s tests

# 4. Lint
python -m ruff check engine backend tests scripts

# 5. Spot-check: items count in range 400-1500
# 6. Spot-check: all 215 source entries present
# 7. Spot-check: knowledge_ids are all unique
# 8. Spot-check: validate_items() returns no errors
```

## Commit Format

```
feat(knowledge): add OpenAccountants GraphRAG ingestion script

Parse 215 OA .md skill files into structured knowledge JSON compatible
with existing ingestion pipeline. Chunks by ## heading, extracts YAML
frontmatter, maps jurisdictions, generates source manifest with
provenance tagging (publisher: "OpenAccountants").

Phase 2 of Three-Stage Rocket (engine audit → GraphRAG → skill accel).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

## Notes for Codex

- **Do NOT modify** any existing files under `backend/`, `engine/`, or `tests/test_m2*.py`. Only create new files.
- The script must work with `python scripts/ingest_openaccountants.py` — handle the import path for `backend.knowledge.ingestion` by adding the project root to `sys.path` if needed.
- If `PyYAML` is not in `requirements.txt`, add it with version pin `>=6.0,<7.0`.
- The `--ingest` flag calls existing `ingest_all()` which handles Neo4j MERGE + Chroma upsert. Do NOT re-implement ingestion logic.
- Generated JSON files should be `.gitignore`d (add `data/knowledge/oa/` and `data/sources/oa/` to `.gitignore`) since they are derived from the OA skill files already in the repo.
- Keep the script under 400 lines. Pure functions. No global state except constants.
