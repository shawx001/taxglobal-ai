"""Response-shape helpers for tax engine functions."""

from __future__ import annotations

from typing import Any

__all__ = ["_response", "_not_covered", "_invalid_input", "_citations", "_merge_citations"]

def _response(
    *,
    status: str,
    input_data: dict[str, Any],
    result: dict[str, Any] | None,
    breakdown: list[dict[str, Any]],
    rule_version: str,
    citations: list[dict[str, Any]],
    assumptions: list[str] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "input": input_data,
        "result": result,
        "breakdown": breakdown,
        "rule_version": rule_version,
        "citations": citations,
        "assumptions": assumptions or [],
        "reason": reason,
    }

def _not_covered(
    *,
    input_data: dict[str, Any],
    rule_version: str,
    reason: str,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _response(
        status="not_covered",
        input_data=input_data,
        result=None,
        breakdown=[],
        rule_version=rule_version,
        citations=citations or [],
        reason=reason,
    )

def _invalid_input(
    *,
    input_data: dict[str, Any],
    rule_version: str,
    reason: str,
    citations: list[dict[str, Any]] | None = None,
    assumptions: list[str] | None = None,
) -> dict[str, Any]:
    return _response(
        status="invalid_input",
        input_data=input_data,
        result=None,
        breakdown=[],
        rule_version=rule_version,
        citations=citations or [],
        assumptions=assumptions,
        reason=reason,
    )

def _citations(*items: dict[str, Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        citation = item.get("citation")
        for source_id in item.get("source_ids", []):
            key = (source_id, citation or "")
            if key not in seen:
                citations.append({"source_id": source_id, "citation": citation})
                seen.add(key)
    return citations

def _merge_citations(*citation_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for citation_list in citation_lists:
        for citation in citation_list:
            key = (citation.get("source_id", ""), citation.get("citation", ""))
            if key not in seen:
                citations.append(citation)
                seen.add(key)
    return citations
