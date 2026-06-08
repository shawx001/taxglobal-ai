"""FastAPI routes for knowledge search."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from backend.knowledge.search import DEFAULT_TOP_K, MAX_TOP_K, hybrid_search

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/search")
def search_knowledge(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    jurisdiction: str | None = Query(None, max_length=10, description="Filter by jurisdiction code"),
    topic: str | None = Query(None, max_length=100, description="Filter by topic"),
    tax_year: int | None = Query(None, ge=2020, le=2030, description="Filter by tax year"),
    top_k: int = Query(DEFAULT_TOP_K, ge=1, le=MAX_TOP_K, description="Max results to return"),
) -> dict[str, Any]:
    """Hybrid knowledge search: vector similarity + graph traversal."""

    return hybrid_search(
        query=q,
        jurisdiction=jurisdiction,
        topic=topic,
        tax_year=tax_year,
        top_k=top_k,
    )
