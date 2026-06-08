# Codex Prompt: M2.3 GraphRAG Retrieval API

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `docs/m2_step_plan.md` §M2.3

## Task

Build a hybrid knowledge-retrieval API that combines **Chroma vector similarity** with **Neo4j graph traversal** to power `GET /api/knowledge/search`. This is the read-side counterpart to M2.2's ingestion pipeline. The endpoint takes a natural-language query (plus optional filters) and returns ranked knowledge items with source citations and related entities from the graph.

Both stores are optional — if one is unavailable, fall back to the other; if both are down, return an empty result list (never error). Existing `/calc/*` endpoints must be completely unaffected.

## Core Constraints

1. **Backward compatibility**: all existing tests and `/calc/*` routes must pass unchanged.
2. **Data sovereignty**: embeddings are computed via the local `embedder` module (already initialized in lifespan); no external API calls.
3. **Graceful degradation**: Neo4j down → vector-only results; Chroma/embedder down → graph-only results; both down → `{"results": [], "total": 0}`.
4. **Stateless + idempotent**: search is pure read; no side effects; safe to retry/cache.
5. **Source provenance**: every returned result **must** include at least one source citation (from the graph's `:Source` node or the Chroma metadata `source_ids` field).
6. **No PII in query logs**: the query string itself is not PII, but do not log any profile data.

## Section 1: Search Module

### File: `backend/knowledge/search.py`

This is the core retrieval module. Three public functions, one orchestrator.

```python
"""Hybrid knowledge search: Chroma vectors + Neo4j graph traversal."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.knowledge import embedder, neo4j_client, vector_store

logger = logging.getLogger("taxglobal.knowledge.search")

DEFAULT_TOP_K = 5
MAX_TOP_K = 20


def vector_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Semantic similarity search via Chroma.

    Returns a list of dicts: {knowledge_id, content, score, metadata}.
    `filters` maps Chroma metadata field names to exact-match values
    (e.g. {"jurisdiction": "CA", "tax_year": 2026}).

    Returns [] if Chroma or embedder is unavailable.
    """
    # 1. Guard: embedder + chroma available?
    # 2. Embed the query text via embedder.embed_text(query)
    # 3. Build a Chroma `where` filter from `filters` dict
    #    - jurisdiction filter should include both the requested value AND "US"
    #      (federal rules always relevant) — use Chroma's $or operator
    #    - tax_year filter is exact-match int
    # 4. collection.query(query_embeddings=[embedding], n_results=top_k, where=where)
    # 5. Map results to standardized dicts with score (Chroma distance → similarity)
    ...


def graph_search(knowledge_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Expand a set of knowledge_ids via Neo4j relationships.

    For each knowledge_id, fetch:
      - APPLIES_TO → Jurisdiction nodes
      - ABOUT → Topic nodes
      - CITED_FROM → Source nodes (title, url, publisher)

    Returns {knowledge_id: {"jurisdictions": [...], "topics": [...], "sources": [...]}}.
    Returns {} if Neo4j is unavailable.
    """
    # Single Cypher query using UNWIND + OPTIONAL MATCH to batch all IDs:
    #
    # UNWIND $ids AS kid
    # MATCH (r:TaxRule {id: kid})
    # OPTIONAL MATCH (r)-[:APPLIES_TO]->(j:Jurisdiction)
    # OPTIONAL MATCH (r)-[:ABOUT]->(t:Topic)
    # OPTIONAL MATCH (r)-[:CITED_FROM]->(s:Source)
    # RETURN r.id AS id, collect(DISTINCT j) AS jurisdictions,
    #        collect(DISTINCT t) AS topics, collect(DISTINCT s) AS sources
    #
    # This avoids N+1 queries — one round-trip regardless of result count.
    ...


def hybrid_search(
    query: str,
    *,
    jurisdiction: str | None = None,
    topic: str | None = None,
    tax_year: int | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    """Orchestrate vector + graph search, merge, deduplicate, and rank.

    Returns the full API response dict:
    {
        "results": [...],
        "total": int,
        "query_metadata": {
            "vector_hits": int,
            "graph_expansions": int,
            "retrieval_method": "hybrid" | "vector_only" | "graph_only" | "none"
        }
    }
    """
    # 1. Clamp top_k to [1, MAX_TOP_K]
    # 2. Build filters dict from jurisdiction/topic/tax_year (skip None values)
    # 3. Call vector_search → get candidate list with scores
    # 4. Extract knowledge_ids from vector hits
    # 5. Call graph_search(knowledge_ids) → get expanded relationships
    # 6. Merge: enrich each vector hit with graph data (sources, topics, jurisdictions, related)
    # 7. Ensure every result has at least one source
    #    - Primary: from graph_search Source nodes
    #    - Fallback: parse source_ids from Chroma metadata JSON string
    # 8. Determine retrieval_method based on what was available
    # 9. Return structured response
    ...
```

**Key implementation details:**

- **Chroma `where` filter for jurisdiction**: When `jurisdiction="CA"`, use `{"$or": [{"jurisdiction": "CA"}, {"jurisdiction": "US"}]}` so federal rules are always included alongside state-specific results.
- **Score normalization**: Chroma returns cosine distance (lower = more similar when using cosine space). Convert to similarity: `score = 1 - distance`. This makes scores intuitive (higher = more relevant).
- **Graph expansion is enrichment, not filtering**: Graph search enriches vector results with relationship data. If Neo4j is down, results still return (from Chroma alone) with source_ids parsed from metadata.
- **Batched Cypher**: Use `UNWIND $ids AS kid` to fetch all expansions in one query, not one query per item.
- **`source_ids` fallback**: Chroma metadata stores `source_ids` as a JSON string (`'["irs_rp_2025_32","irs_pub_501"]'`). When graph is unavailable, parse this to provide source IDs (without full source metadata like title/url).

## Section 2: Search Routes

### File: `backend/knowledge/search_routes.py`

```python
"""FastAPI routes for knowledge search."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from backend.errors import error_response
from backend.knowledge.search import MAX_TOP_K, hybrid_search

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/search")
def search_knowledge(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    jurisdiction: str | None = Query(None, max_length=10, description="Filter by jurisdiction code (e.g. CA, US)"),
    topic: str | None = Query(None, max_length=100, description="Filter by topic"),
    tax_year: int | None = Query(None, ge=2020, le=2030, description="Filter by tax year"),
    top_k: int = Query(5, ge=1, le=MAX_TOP_K, description="Max results to return"),
) -> dict[str, Any]:
    """Hybrid knowledge search: vector similarity + graph traversal."""
    return hybrid_search(
        query=q,
        jurisdiction=jurisdiction,
        topic=topic,
        tax_year=tax_year,
        top_k=top_k,
    )
```

### Wire into `backend/main.py`

In `create_app()`, import and include the search router alongside the existing `calc_router`:

```python
from backend.knowledge.search_routes import router as search_router
# ...
app.include_router(search_router)
```

Place this **after** `app.include_router(calc_router)` to keep the existing routing order.

## Section 3: Response Schema

Each result in the `results` array:

```json
{
  "knowledge_id": "us_2026_feie_maximum",
  "title": "Foreign Earned Income Exclusion (FEIE)",
  "content": "For 2026, the maximum foreign earned income exclusion is $132,900...",
  "jurisdiction": "US",
  "topics": ["foreign_earned_income_exclusion"],
  "sources": [
    {
      "source_id": "irs_rp_2025_32",
      "title": "Revenue Procedure 2025-32",
      "url": "https://www.irs.gov/pub/irs-drop/rp-25-32.pdf",
      "publisher": "Internal Revenue Service"
    }
  ],
  "related_jurisdictions": ["US"],
  "score": 0.87,
  "tax_year": 2026
}
```

**Field rules:**
- `knowledge_id`: from Chroma document ID
- `title`: from Chroma document text (topic portion before `:`) — or from graph `r.title` if available
- `content`: from Chroma document text (summary portion after `:`)
- `sources`: from graph Source nodes; fallback to `source_ids` list from Chroma metadata (without title/url)
- `score`: normalized similarity score (0–1, higher = better)
- `topics` / `related_jurisdictions`: from graph Topic/Jurisdiction nodes; empty list if graph unavailable

## Section 4: Tests

### File: `tests/test_m2_3_search.py`

Use `unittest.mock.patch` to mock the three singletons (`neo4j_client`, `vector_store`, `embedder`) — same pattern as `tests/test_m2_2_ingestion.py`.

**TestVectorSearch** (4 tests):
- `test_vector_search_returns_results`: mock embedder + collection.query → returns list with knowledge_id, content, score
- `test_vector_search_chroma_unavailable_returns_empty`: chroma unavailable → `[]`
- `test_vector_search_embedder_unavailable_returns_empty`: embedder unavailable → `[]`
- `test_vector_search_jurisdiction_filter_includes_federal`: when jurisdiction="CA", the Chroma `where` filter includes `$or` with "US"

**TestGraphSearch** (3 tests):
- `test_graph_search_returns_relationships`: mock run_query → returns jurisdictions, topics, sources per ID
- `test_graph_search_neo4j_unavailable_returns_empty`: neo4j unavailable → `{}`
- `test_graph_search_batched_single_query`: run_query called exactly once (not N times)

**TestHybridSearch** (5 tests):
- `test_hybrid_returns_merged_results`: mock both stores → results have sources + topics from graph + score from vector
- `test_hybrid_vector_only_degradation`: neo4j unavailable → results still returned with source_ids from metadata; `retrieval_method: "vector_only"`
- `test_hybrid_graph_only_degradation`: chroma/embedder unavailable → empty results (graph alone can't rank by query similarity); `retrieval_method: "none"` (acceptable: graph_search needs knowledge_ids from vector_search)
- `test_hybrid_both_unavailable_returns_empty`: both down → `{"results": [], "total": 0, "query_metadata": {"retrieval_method": "none"}}`
- `test_hybrid_clamps_top_k`: top_k=100 → clamped to MAX_TOP_K

**TestSearchRoute** (4 tests — use `fastapi.testclient.TestClient`):
- `test_search_endpoint_returns_200`: mock hybrid_search → 200 with results
- `test_search_missing_query_returns_422`: no `q` param → 422
- `test_search_with_filters`: `?q=FEIE&jurisdiction=US&tax_year=2026` → hybrid_search called with correct params
- `test_search_empty_results`: mock returns empty → `{"results": [], "total": 0}`

**TestSearchDataIntegrity** (3 tests — run against real data files, no mocks):
- `test_knowledge_items_searchable_format`: load `data/knowledge/us/2026/us_core_knowledge.json`, verify all items have fields needed for search (knowledge_id, topic, jurisdiction, summary, source_ids)
- `test_source_manifest_has_urls`: load `data/sources/us/2026/source_manifest.json`, verify sources referenced by knowledge items have `source_url` field
- `test_minimum_topic_diversity`: knowledge items span at least 8 distinct topics (validates search will return varied results)

**Total: ~19 tests.**

## Section 5: Files Changed Summary

| File | Action | Purpose |
|---|---|---|
| `backend/knowledge/search.py` | **NEW** | Core search module: vector_search, graph_search, hybrid_search |
| `backend/knowledge/search_routes.py` | **NEW** | FastAPI router for `GET /api/knowledge/search` |
| `backend/main.py` | **EDIT** | Include search_router in create_app() |
| `tests/test_m2_3_search.py` | **NEW** | ~19 tests covering search, degradation, route, data integrity |

No changes to: `engine/`, `data/`, `backend/routes/calc.py`, `backend/knowledge/ingestion.py`, existing tests.

## Acceptance Gates

```powershell
# All existing + new tests pass
python -m unittest discover -s tests

# Lint clean
python -m ruff check engine backend tests

# No trailing whitespace / merge conflicts
git diff --check
```

Additional verification:
- `GET /api/knowledge/search?q=FEIE` returns results with source citations
- `GET /api/knowledge/search?q=california+tax&jurisdiction=CA` returns CA + US federal results
- `GET /api/knowledge/search?q=nothing_matches_this` returns `{"results": [], "total": 0}`
- `GET /api/health` still returns store status (no regression)
- All existing `/calc/*` endpoints unaffected

## Commit Format

```
feat(knowledge): add GraphRAG hybrid search API (M2.3)

Implement vector similarity (Chroma) + graph traversal (Neo4j) hybrid
search with GET /api/knowledge/search endpoint. Graceful degradation
when either store is unavailable. ~19 tests covering search logic,
degradation paths, route validation, and data integrity.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
