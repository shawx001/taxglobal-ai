"""Workflow nodes and simple M2 parameter extraction."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from backend.guardrail.middleware import GuardrailViolation, guardrail_check
from backend.knowledge.search import hybrid_search
from backend.orchestrator.intent import (
    INTENT_CLARIFY,
    INTENT_CRYPTO,
    INTENT_FEIE,
    INTENT_INCOME_TAX,
    INTENT_KNOWLEDGE,
    INTENT_NEXUS,
    INTENT_RSU,
    INTENT_SKILL_MAP,
    classify_intent,
)
from backend.orchestrator.state import AssistantState
from backend.skills.registry import get_skill
from engine.rules_loader import RuleLoadError

_STATE_CODES = {
    "加州": "CA",
    "纽约": "NY",
    "德州": "TX",
    "佛州": "FL",
    "华盛顿": "WA",
    "马萨诸塞": "MA",
    "伊利诺伊": "IL",
    "新泽西": "NJ",
    "宾州": "PA",
    "俄勒冈": "OR",
    "california": "CA",
    "new york": "NY",
    "texas": "TX",
    "florida": "FL",
    "washington": "WA",
    "massachusetts": "MA",
    "illinois": "IL",
    "new jersey": "NJ",
    "pennsylvania": "PA",
    "oregon": "OR",
}
_NUMBER_PATTERN = re.compile(r"(\d+(?:\.\d+)?)(\s*[万千百])?", re.IGNORECASE)
_STATE_CODE_PATTERN = re.compile(r"\b([A-Z]{2})\b")
_MULTIPLIERS = {"万": Decimal("10000"), "千": Decimal("1000"), "百": Decimal("100")}


def _visited(state: AssistantState, node: str) -> list[str]:
    visited = list(state.get("nodes_visited", []))
    visited.append(node)
    return visited


def _extract_numbers(query: str) -> list[Decimal]:
    numbers: list[Decimal] = []
    for match in _NUMBER_PATTERN.finditer(query):
        value = Decimal(match.group(1))
        suffix = (match.group(2) or "").strip()
        if suffix:
            value *= _MULTIPLIERS.get(suffix, Decimal("1"))
        # Skip values that look like tax years (2020-2040 range) rather than
        # dollar amounts.  The range is intentionally wider than the API's
        # current 2025-2030 window so that adding a new tax year never
        # requires touching this filter.
        int_value = int(value)
        if Decimal("2020") <= value <= Decimal("2040") and value == int_value:
            continue
        numbers.append(value)
    return numbers


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _extract_state(query: str) -> str | None:
    query_lower = query.lower()
    for pattern, code in _STATE_CODES.items():
        if pattern in query_lower:
            return code
    match = _STATE_CODE_PATTERN.search(query)
    return match.group(1) if match else None


def extract_skill_params(query: str, intent: str, tax_year: int = 2026) -> dict[str, Any]:
    """Extract best-effort M2 params from natural language."""

    params: dict[str, Any] = {"tax_year": tax_year}
    state_code = _extract_state(query)
    if state_code:
        params["state_code"] = state_code
    numbers = _extract_numbers(query)
    largest = max(numbers) if numbers else None

    query_lower = query.lower()
    if intent == INTENT_INCOME_TAX and largest is not None:
        if "self-employment" in query_lower or "self employment" in query_lower or "自雇" in query_lower:
            params["net_self_employment_profit"] = _decimal_text(largest)
        else:
            params["w2_wages"] = _decimal_text(largest)
    elif intent == INTENT_FEIE and numbers:
        day_candidates = [int(value) for value in numbers if Decimal("0") <= value <= Decimal("366")]
        income_candidates = [value for value in numbers if value > Decimal("366")]
        if income_candidates:
            params["foreign_earned_income"] = _decimal_text(max(income_candidates))
        if day_candidates:
            params["days_abroad"] = max(day_candidates)
    elif intent == INTENT_NEXUS:
        if largest is not None:
            params["sales_amount"] = _decimal_text(largest)
        transaction_match = re.search(r"(\d+)\s*(transactions?|orders?|笔|单)", query, re.IGNORECASE)
        if transaction_match:
            params["transaction_count"] = int(transaction_match.group(1))

    return params


def _is_self_employment_query(query: str) -> bool:
    """Check if query mentions self-employment keywords."""
    query_lower = query.lower()
    return any(kw in query_lower for kw in ("self-employment", "self employment", "自雇"))


def _missing_params(intent: str, params: dict[str, Any], query: str = "") -> list[str]:
    if intent == INTENT_INCOME_TAX:
        if "w2_wages" in params or "net_self_employment_profit" in params:
            return []
        # Ask for the param that matches the query context.
        if _is_self_employment_query(query):
            return ["net_self_employment_profit"]
        return ["w2_wages"]
    required = {
        INTENT_FEIE: ["foreign_earned_income", "days_abroad"],
        INTENT_RSU: ["shares_vested", "fmv_per_share", "vest_date"],
        INTENT_CRYPTO: ["lots", "disposals"],
        INTENT_NEXUS: ["state_code", "sales_amount"],
    }.get(intent, [])
    return [name for name in required if name not in params]


def classify_node(state: AssistantState) -> dict[str, Any]:
    """Classify user intent from query keywords."""

    result = classify_intent(state["query"])
    return {
        "intent": result.intent,
        "confidence": result.confidence,
        "matched_keyword": result.matched_keyword,
        "nodes_visited": _visited(state, "classify"),
    }


def skill_route_node(state: AssistantState) -> dict[str, Any]:
    """Route a Skill intent to a registered Skill."""

    intent = state.get("intent", "")
    skill_name = INTENT_SKILL_MAP.get(intent, "")
    params = extract_skill_params(state.get("query", ""), intent, int(state.get("tax_year", 2026)))
    missing = _missing_params(intent, params, state.get("query", ""))
    update: dict[str, Any] = {
        "skill_name": skill_name,
        "skill_input": params,
        "nodes_visited": _visited(state, "skill_route"),
    }
    if missing:
        update["missing_params"] = missing
        update["error"] = "missing_skill_params"
        return update

    skill = get_skill(skill_name)
    if skill is None:
        update["error"] = "skill_not_found"
        return update

    try:
        update["skill_output"] = skill.invoke(params)
    except (RuleLoadError, ValidationError) as exc:
        update["error"] = exc.__class__.__name__
    except Exception:
        # Catch-all: unexpected Skill failures become structured errors
        # instead of propagating as 500s.
        update["error"] = "skill_error"
    return update


def kb_route_node(state: AssistantState) -> dict[str, Any]:
    """Route a knowledge intent to GraphRAG hybrid search."""

    try:
        results = hybrid_search(state.get("query", ""), tax_year=int(state.get("tax_year", 2026)), top_k=5)
    except Exception:
        results = {"results": [], "total": 0, "query_metadata": {"retrieval_method": "none"}}
    return {"kb_results": results, "nodes_visited": _visited(state, "kb_route")}


def guardrail_node(state: AssistantState) -> dict[str, Any]:
    """Validate Skill output before formatting."""

    output = state.get("skill_output")
    if output is None:
        return {"guardrail_passed": True, "nodes_visited": _visited(state, "guardrail")}
    try:
        checked = guardrail_check(output, state.get("request_id", ""))
    except GuardrailViolation as exc:
        return {
            "guardrail_passed": False,
            "guardrail_annotation": exc.escalation,
            "error": "guardrail_blocked",
            "nodes_visited": _visited(state, "guardrail"),
        }
    return {
        "skill_output": checked,
        "guardrail_passed": True,
        "guardrail_annotation": checked.get("_guardrail"),
        "nodes_visited": _visited(state, "guardrail"),
    }


def _sources_from_kb(results: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for item in results.get("results", []):
        for source in item.get("sources", []):
            source_id = source.get("source_id") or source.get("title")
            if source_id and source_id not in sources:
                sources.append(str(source_id))
    return sources


def _base_response(state: AssistantState, answer: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    return {
        "intent": state.get("intent", INTENT_CLARIFY),
        "confidence": state.get("confidence", "fallback"),
        "answer": answer,
        "sources": sources,
        "tips": [],
        "trace": {
            "nodes_visited": state.get("nodes_visited", []),
            "matched_keyword": state.get("matched_keyword", ""),
        },
    }


def format_node(state: AssistantState) -> dict[str, Any]:
    """Assemble final structured assistant response."""

    next_state = dict(state)
    next_state["nodes_visited"] = _visited(state, "format")
    error = next_state.get("error")
    if error == "missing_skill_params":
        answer = {
            "type": "clarification",
            "message": "Please provide the missing inputs so I can run the tax engine.",
            "missing_params": next_state.get("missing_params", []),
        }
        return {"response": _base_response(next_state, answer, []), "nodes_visited": next_state["nodes_visited"]}
    if error == "guardrail_blocked":
        answer = {
            "type": "error",
            "message": "The Skill output was blocked by guardrail.",
            "guardrail_passed": False,
        }
        return {"response": _base_response(next_state, answer, []), "nodes_visited": next_state["nodes_visited"]}
    if error:
        answer = {"type": "error", "message": "The assistant workflow could not complete this request."}
        return {"response": _base_response(next_state, answer, []), "nodes_visited": next_state["nodes_visited"]}

    if next_state.get("intent") == INTENT_KNOWLEDGE:
        kb_results = next_state.get("kb_results", {"results": [], "total": 0})
        answer = {"type": "knowledge", "results": kb_results.get("results", []), "total": kb_results.get("total", 0)}
        return {
            "response": _base_response(next_state, answer, _sources_from_kb(kb_results)),
            "nodes_visited": next_state["nodes_visited"],
        }

    skill_output = next_state.get("skill_output", {})
    answer = {
        "type": "skill_result",
        "data": skill_output.get("result", {}),
        "source_attribution": skill_output.get("source_attribution", ""),
        "engine_function": skill_output.get("engine_function", ""),
    }
    sources = [skill_output["source_attribution"]] if skill_output.get("source_attribution") else []
    return {"response": _base_response(next_state, answer, sources), "nodes_visited": next_state["nodes_visited"]}


def clarify_node(state: AssistantState) -> dict[str, Any]:
    """Return a deterministic clarification response."""

    next_state = dict(state)
    next_state["nodes_visited"] = _visited(state, "clarify")
    answer = {
        "type": "clarification",
        "message": (
            "I couldn't determine what you're asking about. Please ask about income tax, "
            "FEIE, RSU, crypto, nexus, or a tax knowledge question."
        ),
        "available_topics": ["income_tax", "feie", "rsu", "crypto", "nexus", "knowledge"],
    }
    return {"response": _base_response(next_state, answer, []), "nodes_visited": next_state["nodes_visited"]}
