"""Assistant workflow graph with LangGraph and a pure-Python fallback."""

from __future__ import annotations

from typing import Any

from backend.orchestrator.intent import INTENT_KNOWLEDGE, INTENT_SKILL_MAP
from backend.orchestrator.nodes import (
    clarify_node,
    classify_node,
    format_node,
    guardrail_node,
    kb_route_node,
    skill_route_node,
)
from backend.orchestrator.state import AssistantState

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    END = None
    StateGraph = None


class _FallbackGraph:
    """Small runner matching the compiled LangGraph invoke surface."""

    def invoke(self, initial_state: AssistantState) -> AssistantState:
        state = _merge(initial_state, classify_node(initial_state))
        route = _route_after_classify(state)
        if route == "skill_route":
            state = _merge(state, skill_route_node(state))
            state = _merge(state, guardrail_node(state))
            return _merge(state, format_node(state))
        if route == "kb_route":
            state = _merge(state, kb_route_node(state))
            return _merge(state, format_node(state))
        return _merge(state, clarify_node(state))


def _merge(state: AssistantState, update: dict[str, Any]) -> AssistantState:
    next_state = dict(state)
    next_state.update(update)
    return next_state


def _route_after_classify(state: AssistantState) -> str:
    intent = state.get("intent", "")
    if intent in INTENT_SKILL_MAP:
        return "skill_route"
    if intent == INTENT_KNOWLEDGE:
        return "kb_route"
    return "clarify"


def build_graph() -> Any:
    """Build and compile the assistant workflow graph."""

    if StateGraph is None:
        return _FallbackGraph()

    graph = StateGraph(AssistantState)
    graph.add_node("classify", classify_node)
    graph.add_node("skill_route", skill_route_node)
    graph.add_node("kb_route", kb_route_node)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("format", format_node)
    graph.add_node("clarify", clarify_node)
    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", _route_after_classify)
    graph.add_edge("skill_route", "guardrail")
    graph.add_edge("guardrail", "format")
    graph.add_edge("kb_route", "format")
    graph.add_edge("format", END)
    graph.add_edge("clarify", END)
    return graph.compile()


def run_assistant_query(
    query: str,
    *,
    profile_id: str = "",
    tax_year: int = 2026,
    request_id: str = "",
) -> dict[str, Any]:
    """Run a query through the deterministic assistant workflow."""

    initial_state: AssistantState = {
        "query": query,
        "profile_id": profile_id,
        "tax_year": tax_year,
        "request_id": request_id,
        "nodes_visited": [],
    }
    final_state = build_graph().invoke(initial_state)
    return final_state["response"]
