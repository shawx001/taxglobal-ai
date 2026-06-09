# Codex Prompt: M2.7 LangGraph Workflow Orchestrator

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `docs/m2_step_plan.md` §M2.7 → `docs/agent_architecture_principles.md`

## Task

Build the deterministic LangGraph workflow that receives a user query, classifies intent via keywords, routes to the correct Skill or Knowledge Base, runs guardrail checks, and formats a structured response. This is the **backbone of the assistant** — M3 will upgrade the classifier to Qwen, but M2 uses pure keyword matching (no LLM).

**Key principle**: "workflow > agent 默认" — this is a **deterministic state machine**, not an autonomous agent. Every branch is explicit code, not model-driven.

## Core Constraints

1. **Backward compatibility**: All existing tests and APIs (`/calc/*`, `/api/skills/*`, `/api/knowledge/search`, `/api/profiles`) must continue to work unchanged.
2. **No LLM**: M2 intent classification = keyword matching; response formatting = template assembly. No model calls.
3. **Data sovereignty**: No external API calls.
4. **Guardrail integration**: Skill outputs must pass through `guardrail_check()` from `backend.guardrail.middleware`.
5. **Graceful degradation**: If Neo4j/Chroma/PG are unavailable, Skill routes still work (they only use the engine); KB routes return empty results (not errors).
6. **Single file ≤ 300 lines**: Split into focused modules.

## Dependencies

Existing code to build on (read these before writing):

| Module | What it provides |
|---|---|
| `backend/skills/registry.py` | `get_skill(name)`, `get_all_skills()`, `get_all_tools()` |
| `backend/skills/base.py` | `TaxSkill`, `TaxSkillResult` — Skill base class + output envelope |
| `backend/guardrail/middleware.py` | `guardrail_check(skill_output, request_id)`, `GuardrailViolation` |
| `backend/guardrail/validator.py` | `check_coverage(topic, state_code)` |
| `backend/knowledge/search.py` | `hybrid_search(query, jurisdiction=, topic=, tax_year=, top_k=)` |
| `backend/main.py` | FastAPI app with `create_app()`, lifespan, routers |

## Section 1: Intent Classifier

### File: `backend/orchestrator/__init__.py`
```python
"""LangGraph workflow orchestrator — deterministic intent routing for M2."""
```

### File: `backend/orchestrator/intent.py`

Keyword-based intent classification. Each intent maps to a list of trigger keywords (Chinese + English). The classifier scans the query for these keywords and returns the best-matching intent.

```python
"""Deterministic keyword-based intent classifier (M2).

M3 will replace this with a Qwen model classifier — keep the interface
stable so graph.py only swaps the classify function.
"""

from __future__ import annotations

from dataclasses import dataclass

# Intent identifiers — these become the routing keys in the state machine.
INTENT_INCOME_TAX = "income_tax"
INTENT_FEIE = "feie"
INTENT_RSU = "rsu"
INTENT_CRYPTO = "crypto"
INTENT_NEXUS = "nexus"
INTENT_KNOWLEDGE = "knowledge"
INTENT_CLARIFY = "clarify"

# Maps intent → list of trigger keywords (case-insensitive substring match).
# Order matters: first match wins; more specific intents before generic "knowledge".
INTENT_KEYWORDS: dict[str, list[str]] = {
    INTENT_FEIE: [
        "feie", "海外收入", "foreign earned", "330天", "330 day",
        "海外工作", "expatriate", "form 2555", "bona fide",
        "physical presence", "海外豁免",
    ],
    INTENT_RSU: [
        "rsu", "restricted stock", "股票归属", "受限股票",
        "vesting", "归属", "equity compensation",
    ],
    INTENT_CRYPTO: [
        "crypto", "加密", "比特币", "bitcoin", "ethereum", "以太坊",
        "capital gain", "资本利得", "coin", "token", "nft",
        "wash sale", "cost basis", "成本基",
    ],
    INTENT_NEXUS: [
        "nexus", "经济联结", "sales tax", "电商", "远程销售",
        "wayfair", "economic nexus", "销售税",
    ],
    INTENT_INCOME_TAX: [
        "所得税", "income tax", "federal tax", "报税", "收入税",
        "州税", "state tax", "交多少税", "税率", "tax rate",
        "标准扣除", "standard deduction", "filing status",
        "自雇税", "self-employment", "fica",
    ],
    INTENT_KNOWLEDGE: [
        "怎么", "什么是", "how", "what is", "when", "deadline",
        "截止", "扣除", "deduction", "抵免", "credit",
        "explain", "解释", "规定", "regulation", "rule",
        "是什么意思", "什么意思",
    ],
}

# Maps Skill intents → Skill registry names (must match backend/skills/registry.py).
INTENT_SKILL_MAP: dict[str, str] = {
    INTENT_INCOME_TAX: "calculate_income_tax",
    INTENT_FEIE: "assess_feie",
    INTENT_RSU: "analyze_rsu",
    INTENT_CRYPTO: "track_crypto",
    INTENT_NEXUS: "detect_nexus",
}


@dataclass
class ClassifyResult:
    """Intent classification output."""
    intent: str
    confidence: str  # "keyword_match" or "fallback"
    matched_keyword: str


def classify_intent(query: str) -> ClassifyResult:
    """Classify a user query into an intent using keyword matching.

    Returns the first matching intent. If no keywords match, falls back
    to INTENT_CLARIFY (ask the user to rephrase).
    """
    query_lower = query.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in query_lower:
                return ClassifyResult(
                    intent=intent,
                    confidence="keyword_match",
                    matched_keyword=keyword,
                )
    return ClassifyResult(
        intent=INTENT_CLARIFY,
        confidence="fallback",
        matched_keyword="",
    )
```

## Section 2: LangGraph State + Nodes

### File: `backend/orchestrator/state.py`

TypedDict state schema for LangGraph. This is the single source of truth for data flowing through the graph.

```python
"""LangGraph state schema — single mutable structure flowing through the graph."""

from __future__ import annotations

from typing import Any, TypedDict


class AssistantState(TypedDict, total=False):
    """State passed between LangGraph nodes.

    All fields are optional (total=False) — nodes populate them progressively.
    """
    # Input
    query: str
    profile_id: str
    tax_year: int
    request_id: str

    # After classify
    intent: str
    confidence: str
    matched_keyword: str

    # After skill_route
    skill_name: str
    skill_input: dict[str, Any]
    skill_output: dict[str, Any]

    # After kb_route
    kb_results: dict[str, Any]

    # After guardrail
    guardrail_passed: bool
    guardrail_annotation: dict[str, Any] | None

    # Final
    response: dict[str, Any]
    error: str | None
    nodes_visited: list[str]
```

### File: `backend/orchestrator/nodes.py`

Each function is a LangGraph node: takes `AssistantState`, returns a partial state update dict. Pure functions (side effects isolated to Skill/KB calls).

Implement these nodes:

1. **`classify_node(state)`** — calls `classify_intent(state["query"])`, returns `{intent, confidence, matched_keyword, nodes_visited: [..., "classify"]}`.

2. **`skill_route_node(state)`** — looks up the Skill via `INTENT_SKILL_MAP` + `get_skill()`, extracts params from the query (best-effort keyword extraction for numbers — e.g., "加州收入15万" → `{"gross_income": 150000, "state": "CA"}`). If the Skill exists, calls `skill.invoke(params)` and stores in `skill_output`. If the Skill is not found or invoke fails, stores an error. Append "skill_route" to `nodes_visited`.

   **Important**: The parameter extraction in M2 is intentionally simple/limited — it extracts obvious numeric values and state codes from the query string. M3's Qwen model will do proper NLU. For M2, if required params can't be extracted, return a clarification response asking for specific inputs.

3. **`kb_route_node(state)`** — calls `hybrid_search(query, ...)` from `backend.knowledge.search`. Stores results in `kb_results`. Append "kb_route" to `nodes_visited`.

4. **`guardrail_node(state)`** — if `skill_output` exists, runs `guardrail_check(skill_output, request_id)`. On `GuardrailViolation`, sets `guardrail_passed=False` + error. Otherwise `guardrail_passed=True`. If no skill_output (KB route), skip and set `guardrail_passed=True`. Append "guardrail" to `nodes_visited`.

5. **`format_node(state)`** — assembles the final structured response dict (see Response Format below). Append "format" to `nodes_visited`.

6. **`clarify_node(state)`** — returns a response asking the user to rephrase with more specific information. Append "clarify" to `nodes_visited`.

**Node implementation pattern**:
```python
def classify_node(state: AssistantState) -> dict[str, Any]:
    """Classify user intent from query keywords."""
    result = classify_intent(state["query"])
    visited = list(state.get("nodes_visited", []))
    visited.append("classify")
    return {
        "intent": result.intent,
        "confidence": result.confidence,
        "matched_keyword": result.matched_keyword,
        "nodes_visited": visited,
    }
```

## Section 3: Graph Assembly

### File: `backend/orchestrator/graph.py`

Assemble the LangGraph `StateGraph`:

```
START → classify_node
         │
         ├─ intent in INTENT_SKILL_MAP → skill_route_node → guardrail_node → format_node → END
         ├─ intent == "knowledge"       → kb_route_node → format_node → END
         └─ intent == "clarify"         → clarify_node → END
```

Use LangGraph conditional edges. The `build_graph()` function returns a compiled graph. If `langgraph` is not importable, provide a simple fallback that runs the nodes sequentially in plain Python (same pattern as `backend/skills/base.py` LangChain fallback).

```python
"""LangGraph StateGraph for the assistant workflow."""

from __future__ import annotations

from typing import Any

from backend.orchestrator.intent import INTENT_CLARIFY, INTENT_KNOWLEDGE, INTENT_SKILL_MAP
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

    def build_graph():
        graph = StateGraph(AssistantState)
        graph.add_node("classify", classify_node)
        graph.add_node("skill_route", skill_route_node)
        graph.add_node("kb_route", kb_route_node)
        graph.add_node("guardrail", guardrail_node)
        graph.add_node("format", format_node)
        graph.add_node("clarify", clarify_node)

        graph.set_entry_point("classify")

        def route_after_classify(state: AssistantState) -> str:
            intent = state.get("intent", "")
            if intent in INTENT_SKILL_MAP:
                return "skill_route"
            if intent == INTENT_KNOWLEDGE:
                return "kb_route"
            return "clarify"

        graph.add_conditional_edges("classify", route_after_classify)
        graph.add_edge("skill_route", "guardrail")
        graph.add_edge("guardrail", "format")
        graph.add_edge("kb_route", "format")
        graph.add_edge("format", END)
        graph.add_edge("clarify", END)

        return graph.compile()

except ImportError:
    # Fallback: run nodes in sequence without LangGraph
    # (same graceful-degradation pattern as skills/base.py)
    # ... implement a simple runner that chains the same nodes
    pass


def run_assistant_query(
    query: str,
    *,
    profile_id: str = "",
    tax_year: int = 2026,
    request_id: str = "",
) -> dict[str, Any]:
    """Public entry point: run the full assistant workflow and return the response."""
    # Build initial state, invoke graph, return state["response"]
    ...
```

## Section 4: Routes

### File: `backend/orchestrator/routes.py`

```python
"""FastAPI routes for the assistant orchestrator."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.orchestrator.graph import run_assistant_query

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AssistantQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    profile_id: str = ""
    tax_year: int = Field(default=2026, ge=2025, le=2030)


@router.post("/query")
def assistant_query(
    request: Request, body: AssistantQueryRequest,
) -> dict[str, Any]:
    """Process a user query through the LangGraph workflow."""
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return run_assistant_query(
        body.query,
        profile_id=body.profile_id,
        tax_year=body.tax_year,
        request_id=request_id,
    )
```

### Update `backend/main.py`

Add the orchestrator router:
```python
from backend.orchestrator.routes import router as orchestrator_router
# ...
app.include_router(orchestrator_router)
```

## Section 5: Response Format

The `/api/assistant/query` response must follow this structure:

```json
{
  "intent": "income_tax",
  "confidence": "keyword_match",
  "answer": {
    "type": "skill_result",
    "data": { ... engine output ... },
    "source_attribution": "IRS / State DOR",
    "engine_function": "income_tax_summary"
  },
  "sources": ["Rev. Proc. 2024-40", "CA FTB"],
  "tips": [],
  "trace": {
    "nodes_visited": ["classify", "skill_route", "guardrail", "format"],
    "matched_keyword": "income tax"
  }
}
```

For KB queries:
```json
{
  "intent": "knowledge",
  "confidence": "keyword_match",
  "answer": {
    "type": "knowledge",
    "results": [ ... hybrid_search results ... ],
    "total": 3
  },
  "sources": ["IRS Pub 17", ...],
  "tips": [],
  "trace": {
    "nodes_visited": ["classify", "kb_route", "format"],
    "matched_keyword": "what is"
  }
}
```

For clarify:
```json
{
  "intent": "clarify",
  "confidence": "fallback",
  "answer": {
    "type": "clarification",
    "message": "I couldn't determine what you're asking about. Please try asking about a specific topic: income tax, FEIE, RSU, crypto, or nexus.",
    "available_topics": ["income_tax", "feie", "rsu", "crypto", "nexus", "knowledge"]
  },
  "sources": [],
  "tips": [],
  "trace": {
    "nodes_visited": ["classify", "clarify"],
    "matched_keyword": ""
  }
}
```

## Section 6: Parameter Extraction (Simple M2 Version)

In `nodes.py`, the `skill_route_node` needs to extract parameters from natural language queries. For M2, implement a simple extractor:

```python
"""Simple parameter extraction from query strings (M2).

M3 replaces this with Qwen NLU. Keep the interface stable.
"""

import re

# State code patterns
_STATE_CODES = {
    "加州": "CA", "纽约": "NY", "德州": "TX", "佛州": "FL",
    "华盛顿": "WA", "马萨诸塞": "MA", "伊利诺伊": "IL",
    "california": "CA", "new york": "NY", "texas": "TX",
    # ... add common ones; can also match bare 2-letter codes
}

_CHINESE_NUMBER_MAP = {"万": 10000, "千": 1000, "百": 100}


def extract_skill_params(query: str, intent: str) -> dict[str, Any]:
    """Best-effort parameter extraction from query text.

    Returns a dict of params that can be passed to the Skill.
    Missing required params → return partial dict (caller decides to clarify).
    """
    params: dict[str, Any] = {}

    # Extract state code
    query_lower = query.lower()
    for pattern, code in _STATE_CODES.items():
        if pattern in query_lower:
            params["state"] = code
            break
    # Also match bare 2-letter state codes
    state_match = re.search(r'\b([A-Z]{2})\b', query)
    if state_match and "state" not in params:
        params["state"] = state_match.group(1)

    # Extract numbers (handle Chinese 万/千)
    # e.g., "收入15万" → 150000, "income 100000" → 100000
    # ... implement number extraction

    # Map extracted numbers to Skill-specific params based on intent
    # e.g., income_tax → gross_income, feie → foreign_earned_income
    # ... implement mapping

    return params
```

This extractor does NOT need to be perfect — it's M2 best-effort. If it can't extract enough params, the skill_route_node should return a clarification response with the specific params needed.

## Section 7: New Tests

### File: `tests/test_m2_7_orchestrator.py`

**Intent Classification Tests** (~8 tests):
- `test_classify_income_tax_english`: "How much income tax do I owe?" → income_tax
- `test_classify_income_tax_chinese`: "加州收入15万交多少税" → income_tax
- `test_classify_feie`: "FEIE 330天测试" → feie
- `test_classify_rsu`: "RSU vesting tax" → rsu
- `test_classify_crypto`: "bitcoin capital gains" → crypto
- `test_classify_nexus`: "economic nexus threshold" → nexus
- `test_classify_knowledge`: "what is standard deduction" → knowledge
- `test_classify_ambiguous_fallback`: "hello" → clarify

**Workflow End-to-End Tests** (~8 tests):
- `test_skill_workflow_income_tax`: Income tax query → classify → skill_route → guardrail → format → response with engine data
- `test_skill_workflow_feie`: FEIE query → full pipeline
- `test_kb_workflow`: Knowledge query → classify → kb_route → format → response with search results
- `test_clarify_workflow`: Ambiguous query → classify → clarify → clarification response
- `test_guardrail_blocks_in_workflow`: Skill returning fabricated output → guardrail blocks → error in response
- `test_trace_records_nodes`: Every response has `trace.nodes_visited` listing all nodes hit
- `test_response_structure`: Response has all required keys (`intent`, `confidence`, `answer`, `sources`, `tips`, `trace`)
- `test_empty_query_rejected`: Empty query → 422 validation error

**Integration Tests** (via FastAPI TestClient, ~5 tests):
- `test_assistant_query_endpoint_200`: POST /api/assistant/query with valid query → 200
- `test_assistant_query_skill_route`: Tax question → Skill result in response
- `test_assistant_query_kb_route`: Knowledge question → KB results in response
- `test_assistant_query_clarify`: Ambiguous → clarification response
- `test_existing_routes_unaffected`: `/calc/federal-income`, `/api/skills`, `/api/knowledge/search` still work

**Parameter Extraction Tests** (~4 tests):
- `test_extract_state_chinese`: "加州" → CA
- `test_extract_state_english`: "California" → CA
- `test_extract_number_chinese`: "收入15万" → 150000
- `test_extract_number_plain`: "income 100000" → 100000

## Acceptance Gates

```powershell
# All tests pass (including new orchestrator tests)
python -m unittest discover -s tests

# Lint clean
python -m ruff check engine backend tests

# No trailing whitespace
git diff --check
```

**Expected**: ~270+ tests (246 existing + ~25 new).

## Commit Format

```
feat(orchestrator): add LangGraph workflow for deterministic assistant routing

Implements M2.7: keyword-based intent classification → Skill/KB routing →
guardrail check → structured response. Uses LangGraph StateGraph with
fallback for environments without langgraph installed.

Depends on: M2.3 (GraphRAG), M2.5 (Skills), M2.6 (Guardrail).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

## What NOT to do

1. **No LLM calls** — M2 is pure keyword matching. Don't import any model or tokenizer.
2. **Don't modify existing Skill routes** — `/api/skills/{name}` stays as-is. The orchestrator is a new parallel entry point.
3. **Don't over-engineer the param extractor** — M3's Qwen model replaces it. Simple regex is fine.
4. **Don't add new dependencies** — `langgraph` is already in requirements.txt. Use it if available, fallback if not.
5. **Don't make a monolith** — split into `intent.py`, `state.py`, `nodes.py`, `graph.py`, `routes.py` (5 files + `__init__.py`).
