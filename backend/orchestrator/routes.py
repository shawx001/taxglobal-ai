"""FastAPI routes for the assistant orchestrator."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.orchestrator.graph import run_assistant_query

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_TEXT_CHUNK_CHARS = 48
_DEFAULT_TAX_YEAR = 2026
_MIN_TAX_YEAR = 2025
_MAX_TAX_YEAR = 2030
_QUERY_YEAR_PATTERN = re.compile(r"(?<!\d)(20[23][0-9])(?!\d)")


class AssistantQueryRequest(BaseModel):
    """Assistant query request body."""

    query: str = Field(..., min_length=1, max_length=2000)
    profile_id: str = ""
    # None = caller did not specify; the year is then inferred from the query
    # text so "2025年加州的所得税" never silently computes with 2026 rules.
    tax_year: int | None = Field(default=None, ge=_MIN_TAX_YEAR, le=_MAX_TAX_YEAR)


def _resolve_tax_year(body: AssistantQueryRequest) -> int:
    if body.tax_year is not None:
        return body.tax_year
    match = _QUERY_YEAR_PATTERN.search(body.query)
    if match:
        year = int(match.group(1))
        if _MIN_TAX_YEAR <= year <= _MAX_TAX_YEAR:
            return year
    return _DEFAULT_TAX_YEAR


@router.post("/query")
def assistant_query(request: Request, body: AssistantQueryRequest) -> dict[str, Any]:
    """Process a user query through the deterministic workflow."""

    request_id = str(getattr(request.state, "request_id", "unknown"))
    return run_assistant_query(
        body.query,
        profile_id=body.profile_id,
        tax_year=_resolve_tax_year(body),
        request_id=request_id,
    )


def _sse_event(event: str, data: Any) -> str:
    """Format one SSE event. JSON-encoding keeps the data on a single line."""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _sse_events(response: dict[str, Any]) -> Iterator[str]:
    """Yield the assistant response as a stream of SSE events.

    The pipeline (including the M3.4 fact-checker) has ALREADY completed
    before streaming starts — we intentionally do not forward raw LLM
    tokens, because the fact-checker needs the full text before it can be
    approved. The verified ``answer_text`` is re-chunked for the frontend
    typing effect.
    """

    meta: dict[str, Any] = {
        "intent": response.get("intent", ""),
        "confidence": response.get("confidence", ""),
        "sources": response.get("sources", []),
        "trace": response.get("trace", {}),
    }
    if "fact_check" in response:
        meta["fact_check"] = response["fact_check"]
    yield _sse_event("meta", meta)
    yield _sse_event("answer", response.get("answer", {}))

    text = response.get("answer_text")
    if isinstance(text, str) and text:
        for start in range(0, len(text), _TEXT_CHUNK_CHARS):
            yield _sse_event("text", {"delta": text[start : start + _TEXT_CHUNK_CHARS]})

    yield _sse_event("done", {"ok": True})


@router.post("/stream")
def assistant_stream(request: Request, body: AssistantQueryRequest) -> StreamingResponse:
    """SSE endpoint for the Copilot chat UI (M3.5).

    Works identically with ``ENABLE_LLM`` on or off: with the flag off the
    stream simply carries no ``text`` events and the frontend renders the
    structured answer. ``/query`` remains the plain-JSON endpoint.
    """

    request_id = str(getattr(request.state, "request_id", "unknown"))
    response = run_assistant_query(
        body.query,
        profile_id=body.profile_id,
        tax_year=_resolve_tax_year(body),
        request_id=request_id,
    )
    return StreamingResponse(
        _sse_events(response),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
