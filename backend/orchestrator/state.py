"""LangGraph state schema for assistant workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class AssistantState(TypedDict, total=False):
    """State passed between orchestrator nodes."""

    query: str
    profile_id: str
    tax_year: int
    request_id: str
    intent: str
    confidence: str
    matched_keyword: str
    skill_name: str
    skill_input: dict[str, Any]
    skill_output: dict[str, Any]
    kb_results: dict[str, Any]
    guardrail_passed: bool
    guardrail_annotation: dict[str, Any] | None
    response: dict[str, Any]
    error: str | None
    missing_params: list[str]
    nodes_visited: list[str]
