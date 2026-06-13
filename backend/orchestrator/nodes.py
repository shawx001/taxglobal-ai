"""Workflow nodes and simple M2 parameter extraction."""

from __future__ import annotations

import logging
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

logger = logging.getLogger("taxglobal.orchestrator")

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
# Digits glued to letters are NOT amounts: "W2"/"W-2"/"401k" must never
# become wages (live bug 2026-06-11: "我有W2" → w2_wages=2.00). A hyphen
# only blocks when it follows a LETTER ("W-2") — digit ranges like
# "10-20万" must still parse (both bounds; largest wins downstream).
# Comma-grouped amounts ("100,000") parse as one number. Note: standalone
# form numbers with a space ("Form 1040") still parse on this regex path;
# the LLM extraction layer handles those when enabled.
_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.,])(?<![A-Za-z]-)(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(\s*[万千百])?(?![A-Za-z0-9])"
)
_STATE_CODE_PATTERN = re.compile(r"\b([A-Z]{2})\b")
_MULTIPLIERS = {"万": Decimal("10000"), "千": Decimal("1000"), "百": Decimal("100")}


def _visited(state: AssistantState, node: str) -> list[str]:
    visited = list(state.get("nodes_visited", []))
    visited.append(node)
    return visited


def _extract_numbers(query: str) -> list[Decimal]:
    numbers: list[Decimal] = []
    for match in _NUMBER_PATTERN.finditer(query):
        value = Decimal(match.group(1).replace(",", ""))
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
    """Classify user intent — LLM-enhanced when available, keyword fallback."""

    query = state["query"]

    # Try LLM classification first (returns None if ENABLE_LLM=false or LLM fails)
    from backend import config

    if config.ENABLE_LLM:
        from backend.orchestrator.intent import llm_classify_intent

        llm_result = llm_classify_intent(query)
        if llm_result is not None:
            return {
                "intent": llm_result.intent,
                "confidence": llm_result.confidence,
                "matched_keyword": llm_result.matched_keyword,
                "nodes_visited": _visited(state, "classify"),
            }

    # Fallback: M2 keyword classification (always available)
    result = classify_intent(query)
    return {
        "intent": result.intent,
        "confidence": result.confidence,
        "matched_keyword": result.matched_keyword,
        "nodes_visited": _visited(state, "classify"),
    }


def _extract_params_for_route(state: AssistantState, intent: str) -> dict[str, Any]:
    """LLM extraction first (understands language), regex as fallback."""

    query = state.get("query", "")
    tax_year = int(state.get("tax_year", 2026))

    from backend import config

    if config.ENABLE_LLM:
        from backend.orchestrator.extraction import llm_extract_params

        llm_params = llm_extract_params(query, intent)
        if llm_params is not None:
            params: dict[str, Any] = {"tax_year": tax_year}
            params.update(llm_params)
            return params
    return extract_skill_params(query, intent, tax_year)


def skill_route_node(state: AssistantState) -> dict[str, Any]:
    """Route a Skill intent to a registered Skill."""

    intent = state.get("intent", "")
    skill_name = INTENT_SKILL_MAP.get(intent, "")
    params = _extract_params_for_route(state, intent)
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


# Phrasings that ask about the tax SYSTEM (rates/brackets), not a personal
# calculation. "我有W2" must NOT land here — it gets a conversational ask.
_RATES_QUERY_PATTERN = re.compile(r"税率|税多少|多少税|交多少|bracket|rate", re.IGNORECASE)


def _rate_overview_answer(state: AssistantState) -> dict[str, Any] | None:
    """Build a rates-overview answer from rule data for amount-less queries.

    Only the income_tax intent qualifies: a missing wage/SE amount means
    the user asked about the tax system, not their own liability. Other
    intents (RSU/crypto/nexus) genuinely need their inputs.
    """

    if state.get("intent") != INTENT_INCOME_TAX:
        return None
    if not _RATES_QUERY_PATTERN.search(state.get("query", "")):
        return None
    missing = set(state.get("missing_params", []))
    if not missing & {"w2_wages", "net_self_employment_profit"}:
        return None

    from engine.overview import federal_tax_overview, state_tax_overview
    from engine.rules_loader import RuleLoadError

    state_code = _extract_state(state.get("query", ""))
    tax_year = int(state.get("tax_year", 2026))
    try:
        if state_code:
            overview = state_tax_overview(state_code, tax_year)
        else:
            overview = federal_tax_overview(tax_year)
    except RuleLoadError:
        return None
    except Exception:
        return None

    answer = {"type": "tax_overview", "data": overview}
    sources = [overview["citation"]] if overview.get("citation") else list(overview.get("source_ids", []))
    return {"answer": answer, "sources": sources}


def _attach_llm_answer_text(response: dict[str, Any], query: str) -> dict[str, Any]:
    """M3.3: add a natural-language ``answer_text`` when the LLM is enabled.

    The structured ``answer`` is never modified — any LLM failure simply
    leaves the M2 template response unchanged.
    """

    from backend import config

    if not config.ENABLE_LLM:
        return response

    from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity
    from backend.orchestrator.response import llm_format_response

    answer = response.get("answer", {})
    sources = response.get("sources", [])
    text = llm_format_response(query, answer, sources)
    if text is None:
        return response

    fact_check = check_response_fidelity(text, answer, sources)
    if fact_check.verdict == VERDICT_BLOCK:
        # Validator-feedback retry: one rewrite with explicit instructions,
        # then fail closed. Rescues drafts where the LLM slipped in a
        # from-memory figure on no-number answers (clarifications).
        text = llm_format_response(
            query,
            answer,
            sources,
            retry_feedback=(
                "Your previous draft was REJECTED: it contained a monetary "
                "figure that does not appear in ENGINE_RESULT. Rewrite the "
                "answer WITHOUT any monetary figures except those copied "
                "exactly from ENGINE_RESULT — in any format ($X, X万美元, Xk)."
            ),
        )
        if text is not None:
            fact_check = check_response_fidelity(text, answer, sources)
    if text is None or fact_check.verdict == VERDICT_BLOCK:
        logger.warning("fact-checker blocked LLM answer_text: %s", ",".join(fact_check.issues))
        return response

    response["answer_text"] = text
    response["fact_check"] = {"verdict": fact_check.verdict, "issues": fact_check.issues}
    return response


def format_node(state: AssistantState) -> dict[str, Any]:
    """Assemble final structured assistant response."""

    next_state = dict(state)
    next_state["nodes_visited"] = _visited(state, "format")
    error = next_state.get("error")
    if error == "missing_skill_params":
        # "加州税多少" without an income amount is a RATES question, not a
        # calculation request — answer it from the versioned rule data
        # instead of dead-ending on a parameter prompt.
        overview = _rate_overview_answer(next_state)
        if overview is not None:
            return {
                "response": _base_response(next_state, overview["answer"], overview["sources"]),
                "nodes_visited": next_state["nodes_visited"],
            }
        answer = {
            "type": "clarification",
            "message": "Please provide the missing inputs so I can run the tax engine.",
            "missing_params": next_state.get("missing_params", []),
        }
        response = _base_response(next_state, answer, [])
        return {
            "response": _attach_llm_answer_text(response, next_state.get("query", "")),
            "nodes_visited": next_state["nodes_visited"],
        }
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

    query = next_state.get("query", "")
    if next_state.get("intent") == INTENT_KNOWLEDGE:
        kb_results = next_state.get("kb_results", {"results": [], "total": 0})
        answer = {
            "type": "knowledge",
            "results": kb_results.get("results", []),
            "total": kb_results.get("total", 0),
            # CRAG retrieval confidence (C.2) — drives honest "no KB entry"
            # phrasing downstream when low/unknown.
            "confidence": kb_results.get("query_metadata", {}).get("confidence", "unknown"),
        }
        response = _base_response(next_state, answer, _sources_from_kb(kb_results))
        return {
            "response": _attach_llm_answer_text(response, query),
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
    response = _base_response(next_state, answer, sources)
    return {"response": _attach_llm_answer_text(response, query), "nodes_visited": next_state["nodes_visited"]}


def clarify_node(state: AssistantState) -> dict[str, Any]:
    """Return a clarification response — conversational when the LLM is on.

    Small talk ("你是谁") lands here; with ENABLE_LLM the reply is generated
    naturally (and still fact-checked), with the template as fallback.
    """

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
    response = _base_response(next_state, answer, [])
    return {
        "response": _attach_llm_answer_text(response, next_state.get("query", "")),
        "nodes_visited": next_state["nodes_visited"],
    }
