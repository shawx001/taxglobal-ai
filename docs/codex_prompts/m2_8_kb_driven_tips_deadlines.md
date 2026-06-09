# Codex Prompt: M2.8 KB-Driven Tax Tips & Deadlines

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `docs/m2_step_plan.md` §M2.8

## Task

Build a **deterministic, knowledge-base-driven** tips and deadlines API that returns
personalised tax reminders based on a user's profile data (state, income type, filing
status) and upcoming federal/state deadlines. No LLM — all matching is rule-based
against the existing `us_core_knowledge.json` items and their `trigger_conditions`.

The endpoint is `GET /api/tips` with optional `profile_id` and direct query params.
When PostgreSQL is unavailable (or no `profile_id`), the endpoint still works by
accepting inline params (`state`, `filing_status`, `income_types`) and returning
generic tips + deadlines.

## Core Constraints

1. **Backward compatibility**: existing tests/APIs (`/calc/*`, `/api/skills`, `/api/assistant/query`, `/api/knowledge/search`, `/api/profiles`) must not break.
2. **Data sovereignty**: no external API calls. All data from local knowledge JSON + Neo4j/Chroma.
3. **Graceful degradation**: Neo4j/Chroma/PostgreSQL all optional. When all down, return hardcoded federal deadlines from knowledge JSON (loaded at import time).
4. **No LLM**: pure Python matching logic.
5. **Module size**: no single file > 500 lines; prefer 200-300.

## Architecture

```
GET /api/tips?profile_id=...&state=CA&filing_status=single&income_types=self_employment,foreign
         │
         ▼
    ┌─────────────┐
    │  resolve     │  profile_id → load from PG (optional)
    │  profile     │  OR use inline query params
    └──────┬──────┘
           │ TipContext(state, filing_status, income_types, tax_year)
           ▼
    ┌─────────────┐
    │  match_tips  │  scan knowledge items → check trigger_conditions
    └──────┬──────┘  against TipContext → score by relevance
           │
           ▼
    ┌─────────────┐
    │  deadlines   │  filter deadline items by context
    └──────┬──────┘  sort by date
           │
           ▼
    { tips: [...], deadlines: [...], profile_used: true/false }
```

## Section 1: Knowledge Tip Matcher

### File: `backend/knowledge/tips.py` (~200 lines)

This module loads knowledge items and matches them against a user context.

```python
"""KB-driven tax tips and deadline matching."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger("taxglobal.knowledge.tips")

# --- TipContext: the user's profile distilled for matching ---

@dataclass(frozen=True)
class TipContext:
    """Immutable context for tip matching."""
    state: str = ""                          # 2-letter code, e.g. "CA"
    filing_status: str = "single"
    income_types: tuple[str, ...] = ()       # e.g. ("w2", "self_employment", "foreign")
    tax_year: int = 2026
    has_crypto: bool = False
    has_rsu: bool = False


# --- Load knowledge items at module level (cheap, ~80 items) ---

_KNOWLEDGE_ITEMS: list[dict[str, Any]] = []

def _load_knowledge() -> list[dict[str, Any]]:
    """Load items from the 2026 knowledge JSON. Called once at import."""
    # Use same path pattern as ingestion.py
    path = Path("data/knowledge/us/2026/us_core_knowledge.json")
    if not path.is_file():
        logger.warning("Knowledge file not found: %s", path)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("items", [])
    except Exception:
        logger.exception("Failed to load knowledge items")
        return []

_KNOWLEDGE_ITEMS = _load_knowledge()


def _matches_trigger(trigger: dict[str, Any], ctx: TipContext) -> bool:
    """Check if a single trigger_conditions dict matches the context."""
    # Implement matching logic — see design notes below.
    # Each key in trigger is a condition; ALL must be satisfied (AND).
    # ...
    pass


def _relevance_score(item: dict[str, Any], ctx: TipContext) -> float:
    """Score 0.0-1.0: how relevant is this item to the context."""
    # Higher for: matching state, matching income type, deadline proximity
    # ...
    pass


def get_tips(ctx: TipContext, *, max_tips: int = 10) -> list[dict[str, Any]]:
    """Return ranked tips matching the context."""
    # Filter _KNOWLEDGE_ITEMS by trigger match, exclude deadline items,
    # score, sort descending, cap at max_tips.
    # Each tip: {knowledge_id, title, summary, topic, relevance, sources}
    pass


def get_deadlines(ctx: TipContext) -> list[dict[str, Any]]:
    """Return upcoming deadlines sorted by date."""
    # Filter items where topic == "deadline", match trigger_conditions,
    # parse date from trigger_conditions or summary,
    # sort by date ascending.
    # Each deadline: {knowledge_id, title, date, summary, applies_to, sources}
    pass
```

**Trigger matching rules** (implement in `_matches_trigger`):

| trigger key | match logic |
|---|---|
| `tax_year` | `trigger["tax_year"] == ctx.tax_year` |
| `state` | `trigger["state"] == ctx.state` (case-insensitive) |
| `filing_status` | `trigger["filing_status"] == ctx.filing_status` |
| `self_employment_income` | `"self_employment" in ctx.income_types` |
| `foreign_earned_income` | `"foreign" in ctx.income_types` |
| `w2_wages` | `"w2" in ctx.income_types` |
| `digital_asset_sale`, `staking_rewards`, `nft_sale` | `ctx.has_crypto` |
| `rsu_vesting`, `rsu_sale` | `ctx.has_rsu` |
| `estimated_tax_required` | `"self_employment" in ctx.income_types` |
| `taxpayer_abroad` | `"foreign" in ctx.income_types` |
| `high_income` | always True (can't determine from context — include as lower relevance) |
| `taxable_income_over` | skip (can't check without full calc — include at lower relevance) |
| unrecognized key | skip (don't fail, just don't boost) |

A trigger with **no conditions** or only `tax_year` → generic tip, always matches.

**Relevance scoring** heuristics:
- State-specific match (item jurisdiction == ctx.state): +0.3
- Income-type match (item topic relates to ctx income): +0.3
- Deadline proximity (< 90 days): +0.2
- Has source_ids: +0.1
- Generic federal tip: base 0.3

**Deadline date extraction**: knowledge items with topic `"deadline"` have dates
in `trigger_conditions` (e.g. `estimated_tax_installment: "q2"`) or summaries
mentioning specific dates. Map known patterns:
- `deadline_type: "filing"` → April 15 of tax_year
- `estimated_tax_installment: "q1"` → April 15
- `estimated_tax_installment: "q2"` → June 15
- `estimated_tax_installment: "q3"` → September 15
- `estimated_tax_installment: "q4"` → January 15 of tax_year+1
- `extension_requested: true` → October 15
- `information_return: "w2"` → January 31
- `information_return: "1099"` → January 31
- `taxpayer_abroad: true` → June 15 (auto 2-month extension)

Store these as a `_DEADLINE_DATE_MAP` dict for clean lookup.

## Section 2: Profile Resolution

### In `backend/knowledge/tips.py` or separate helper

```python
def context_from_profile(profile_data: dict[str, Any], tax_year: int = 2026) -> TipContext:
    """Build TipContext from a profile's data JSONB."""
    # Extract state, filing_status, detect income types from profile keys
    # Profile data shape (from M2.4 schemas.py ProfileCreate):
    #   {"filing_status": "single", "state": "CA",
    #    "gross_income": 150000, "self_employment_income": 50000, ...}
    # Detect income types:
    #   - "w2" if gross_income or w2_wages present and > 0
    #   - "self_employment" if self_employment_income or net_self_employment_profit > 0
    #   - "foreign" if foreign_earned_income > 0
    #   - has_crypto if crypto-related keys present
    #   - has_rsu if rsu-related keys present
    pass


def context_from_params(
    state: str = "",
    filing_status: str = "single",
    income_types: str = "",
    tax_year: int = 2026,
) -> TipContext:
    """Build TipContext from direct query params."""
    types = tuple(t.strip() for t in income_types.split(",") if t.strip())
    return TipContext(
        state=state.upper(),
        filing_status=filing_status,
        income_types=types,
        tax_year=tax_year,
        has_crypto="crypto" in types,
        has_rsu="rsu" in types,
    )
```

## Section 3: API Route

### File: `backend/knowledge/tips_routes.py` (~80 lines)

```python
"""FastAPI routes for KB-driven tips and deadlines."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from backend.database import get_session, is_pg_available
from backend.knowledge.tips import (
    TipContext,
    context_from_params,
    context_from_profile,
    get_deadlines,
    get_tips,
)

router = APIRouter(prefix="/api/tips", tags=["tips"])


async def _tips_session() -> Any:
    """Yield DB session or None when PG unavailable."""
    if not is_pg_available():
        yield None
        return
    async for session in get_session():
        yield session


@router.get("")
async def tips_and_deadlines(
    request: Request,
    profile_id: str | None = Query(None, description="Profile UUID to load context from"),
    state: str = Query("", max_length=2, description="2-letter state code"),
    filing_status: str = Query("single", description="Filing status"),
    income_types: str = Query("", description="Comma-separated: w2,self_employment,foreign,crypto,rsu"),
    tax_year: int = Query(2026, ge=2025, le=2030),
    session: Any = Depends(_tips_session),
) -> dict[str, Any]:
    """Return personalised tips + upcoming deadlines."""

    profile_used = False
    ctx: TipContext

    # Try profile first if profile_id given and PG available
    if profile_id and session is not None:
        # Import here to avoid circular dep
        from backend.profiles.service import get_profile_by_id
        import uuid as _uuid
        try:
            profile = await get_profile_by_id(session, _uuid.UUID(profile_id))
            if profile is not None:
                ctx = context_from_profile(profile.data, tax_year)
                profile_used = True
        except Exception:
            pass  # fall through to params

    if not profile_used:
        ctx = context_from_params(state, filing_status, income_types, tax_year)

    tips = get_tips(ctx)
    deadlines = get_deadlines(ctx)

    return {
        "tips": tips,
        "deadlines": deadlines,
        "profile_used": profile_used,
        "context": {
            "state": ctx.state,
            "filing_status": ctx.filing_status,
            "income_types": list(ctx.income_types),
            "tax_year": ctx.tax_year,
        },
    }
```

### Wire into `backend/main.py`

Add after the orchestrator router import:
```python
from backend.knowledge.tips_routes import router as tips_router
# ...
app.include_router(tips_router)
```

## Section 4: Tests

### File: `tests/test_m2_8_tips.py` (~250 lines)

```python
class TestTipContext(unittest.TestCase):
    """TipContext construction from params and profile data."""

    def test_context_from_params_basic(self):
        ctx = context_from_params(state="CA", filing_status="single", income_types="w2,self_employment")
        assert ctx.state == "CA"
        assert ctx.filing_status == "single"
        assert ctx.income_types == ("w2", "self_employment")

    def test_context_from_params_empty(self):
        ctx = context_from_params()
        assert ctx.state == ""
        assert ctx.income_types == ()

    def test_context_from_profile_data(self):
        data = {"filing_status": "married_filing_jointly", "state": "NY",
                "gross_income": 200000, "self_employment_income": 50000}
        ctx = context_from_profile(data)
        assert ctx.state == "NY"
        assert "self_employment" in ctx.income_types


class TestTipMatcher(unittest.TestCase):
    """Trigger matching and relevance scoring."""

    def test_self_employment_gets_estimated_tax_tip(self):
        ctx = TipContext(income_types=("self_employment",))
        tips = get_tips(ctx)
        topics = [t["topic"] for t in tips]
        assert "estimated_tax" in topics or "self_employment_tax" in topics

    def test_foreign_income_gets_feie_tip(self):
        ctx = TipContext(income_types=("foreign",))
        tips = get_tips(ctx)
        ids = [t["knowledge_id"] for t in tips]
        assert any("feie" in kid for kid in ids)

    def test_ma_high_income_gets_surtax_tip(self):
        ctx = TipContext(state="MA")
        tips = get_tips(ctx)
        ids = [t["knowledge_id"] for t in tips]
        assert any("surtax" in kid for kid in ids)

    def test_wa_gets_capital_gains_excise_tip(self):
        ctx = TipContext(state="WA")
        tips = get_tips(ctx)
        ids = [t["knowledge_id"] for t in tips]
        assert any("wa" in kid.lower() for kid in ids)

    def test_empty_context_gets_generic_tips(self):
        ctx = TipContext()
        tips = get_tips(ctx)
        assert len(tips) > 0  # should return generic federal tips

    def test_tips_have_required_fields(self):
        ctx = TipContext(state="CA", income_types=("w2",))
        tips = get_tips(ctx)
        for tip in tips:
            assert "knowledge_id" in tip
            assert "topic" in tip
            assert "summary" in tip
            assert "sources" in tip

    def test_tips_sorted_by_relevance(self):
        ctx = TipContext(state="CA", income_types=("self_employment",))
        tips = get_tips(ctx)
        if len(tips) >= 2:
            assert tips[0]["relevance"] >= tips[1]["relevance"]

    def test_max_tips_cap(self):
        ctx = TipContext()
        tips = get_tips(ctx, max_tips=3)
        assert len(tips) <= 3


class TestDeadlines(unittest.TestCase):
    """Deadline extraction and sorting."""

    def test_deadlines_include_april_filing(self):
        ctx = TipContext()
        deadlines = get_deadlines(ctx)
        titles = " ".join(d.get("title", "") + d.get("summary", "") for d in deadlines)
        assert "April 15" in titles or "april" in titles.lower()

    def test_deadlines_sorted_by_date(self):
        ctx = TipContext()
        deadlines = get_deadlines(ctx)
        dates = [d["date"] for d in deadlines if d.get("date")]
        assert dates == sorted(dates)

    def test_self_employed_sees_estimated_deadlines(self):
        ctx = TipContext(income_types=("self_employment",))
        deadlines = get_deadlines(ctx)
        summaries = " ".join(d.get("summary", "") for d in deadlines)
        assert "estimated" in summaries.lower()

    def test_foreign_sees_june_extension(self):
        ctx = TipContext(income_types=("foreign",))
        deadlines = get_deadlines(ctx)
        summaries = " ".join(d.get("summary", "") for d in deadlines)
        assert "abroad" in summaries.lower() or "June" in summaries

    def test_deadlines_have_required_fields(self):
        ctx = TipContext()
        deadlines = get_deadlines(ctx)
        for d in deadlines:
            assert "knowledge_id" in d
            assert "summary" in d
            assert "date" in d
            assert "sources" in d


class TestTipsRoutes(unittest.TestCase):
    """API endpoint integration tests."""

    def setUp(self):
        from backend.main import create_app
        from fastapi.testclient import TestClient
        self.client = TestClient(create_app())

    def test_tips_endpoint_200(self):
        response = self.client.get("/api/tips")
        assert response.status_code == 200
        data = response.json()
        assert "tips" in data
        assert "deadlines" in data
        assert "profile_used" in data
        assert "context" in data

    def test_tips_with_state_param(self):
        response = self.client.get("/api/tips?state=CA&income_types=w2")
        assert response.status_code == 200
        data = response.json()
        assert data["context"]["state"] == "CA"

    def test_tips_self_employment(self):
        response = self.client.get("/api/tips?income_types=self_employment")
        assert response.status_code == 200
        tips = response.json()["tips"]
        topics = [t["topic"] for t in tips]
        assert any("self_employment" in t or "estimated" in t for t in topics)

    def test_existing_routes_unaffected(self):
        """All existing endpoints still work after adding tips router."""
        calc = self.client.post("/calc/federal-income",
            json={"gross_income": 100000, "filing_status": "single", "tax_year": 2026})
        skills = self.client.get("/api/skills")
        search = self.client.get("/api/knowledge/search", params={"q": "FEIE"})
        assistant = self.client.post("/api/assistant/query", json={"query": "hello"})
        assert calc.status_code == 200
        assert skills.status_code == 200
        assert search.status_code == 200
        assert assistant.status_code == 200
```

## Acceptance Gates

```powershell
# All tests pass (existing + new)
python -m unittest discover -s tests

# Lint clean
python -m ruff check engine backend tests

# No uncommitted changes
git diff --check

# Specific: new tips endpoint returns 200
python -c "from fastapi.testclient import TestClient; from backend.main import create_app; c=TestClient(create_app()); r=c.get('/api/tips'); print(r.status_code, len(r.json()['tips']), 'tips', len(r.json()['deadlines']), 'deadlines')"
```

## File Summary

| File | Action | ~Lines |
|---|---|---|
| `backend/knowledge/tips.py` | **New** | ~200 |
| `backend/knowledge/tips_routes.py` | **New** | ~80 |
| `backend/main.py` | **Edit** — add tips router import + include | +3 |
| `tests/test_m2_8_tips.py` | **New** | ~250 |

**Total new code**: ~530 lines across 3 new files + 3-line edit.

## Commit Format

```
feat(knowledge): M2.8 KB-driven tips and deadlines API

Add GET /api/tips endpoint returning personalised tax tips and upcoming
deadlines matched from knowledge base trigger_conditions against user
profile or inline query params. Graceful degradation when PG/Neo4j/Chroma
unavailable — falls back to static knowledge JSON loaded at import time.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
