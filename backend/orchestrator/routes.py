"""FastAPI routes for the assistant orchestrator."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.orchestrator.graph import run_assistant_query

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AssistantQueryRequest(BaseModel):
    """Assistant query request body."""

    query: str = Field(..., min_length=1, max_length=2000)
    profile_id: str = ""
    tax_year: int = Field(default=2026, ge=2025, le=2030)


@router.post("/query")
def assistant_query(request: Request, body: AssistantQueryRequest) -> dict[str, Any]:
    """Process a user query through the deterministic workflow."""

    request_id = str(getattr(request.state, "request_id", "unknown"))
    return run_assistant_query(
        body.query,
        profile_id=body.profile_id,
        tax_year=body.tax_year,
        request_id=request_id,
    )
