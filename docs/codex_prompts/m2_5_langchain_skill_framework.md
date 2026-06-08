# Codex Prompt: M2.5 LangChain Skill Framework + 5 Engine Skills

> Pre-read: `/AGENTS.md` -> `/ARCHITECTURE.md` -> `docs/m2_step_plan.md` section M2.5

## Task

Wrap the 5 existing engine pure functions as LangChain `BaseTool` subclasses, register them in a unified Skill registry, and expose two new API endpoints: `GET /api/skills` (list all) and `POST /api/skills/{name}` (invoke one). This creates the tool interface that M2.7 LangGraph Workflow will call — engine functions become first-class callable tools in the LangChain ecosystem.

The engine functions already exist and are battle-tested (191 tests green). This step is a **thin wrapper layer** — it calls into `engine/` pure functions, adds Pydantic input validation and standardized output formatting (source attribution + engine trace), and registers them for programmatic discovery. No engine logic changes.

Existing `/calc/*` endpoints, `/api/knowledge/search`, and `/api/profiles` must be completely unaffected.

## Core Constraints

1. **Backward compatibility**: all 191 existing tests and all existing routes must pass unchanged. Engine module `engine/` is read-only — do NOT modify any file under `engine/`.
2. **No new dependencies**: `langchain-core` is already in `backend/requirements.txt`. Use `langchain_core.tools.BaseTool` (or `StructuredTool`). Do NOT add any other LangChain packages.
3. **Engine is the only truth**: Skills call engine pure functions directly. The Skill layer does NOT compute any tax amount itself — it validates input, calls the engine, and formats the output. Any amount in the response MUST originate from the engine function return value.
4. **Decimal-safe output**: Engine functions return `str` amounts (already formatted). Skills must NOT do any float arithmetic or re-format monetary values. Pass them through as-is.
5. **Graceful degradation**: Skills do NOT depend on any database (PG, Neo4j, Chroma). They only call `engine/` pure functions. If the engine raises `RuleLoadError` for an unsupported tax year, the Skill should propagate the error (not swallow it).
6. **Data sovereignty**: No external API calls. Everything runs locally.
7. **Stateless + idempotent**: Skills are pure wrappers around pure functions. No side effects.

## Section 1: Skill Base Class

### File: `backend/skills/base.py`

Define a base class that all tax Skills inherit from. The base class standardizes:
- Input validation via a Pydantic `args_schema`
- Engine call delegation to a subclass method
- Output wrapping with `source_attribution` and `engine_trace` metadata

```python
"""Base class for LangChain-compatible tax calculation skills."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

from langchain_core.tools import BaseTool
from pydantic import BaseModel


class TaxSkillResult(BaseModel):
    """Standardized Skill output envelope."""

    status: str
    result: dict[str, Any]
    source_attribution: str
    engine_function: str


class TaxSkill(BaseTool):
    """Base for all tax calculation skills.

    Subclasses set:
      - name, description (LangChain required)
      - args_schema (Pydantic model for input validation)
      - source_attribution (e.g. "Rev. Proc. 2024-40")
      - engine_function_name (e.g. "income_tax_summary")
    And implement _execute_engine(validated_input) -> dict.
    """

    source_attribution: ClassVar[str] = ""
    engine_function_name: ClassVar[str] = ""

    def _run(self, **kwargs: Any) -> dict[str, Any]:
        """Validate -> call engine -> wrap result."""
        engine_result = self._execute_engine(kwargs)
        return {
            "status": engine_result.get("status", "ok"),
            "result": engine_result,
            "source_attribution": self.source_attribution,
            "engine_function": self.engine_function_name,
        }

    @abstractmethod
    def _execute_engine(self, params: dict[str, Any]) -> dict[str, Any]:
        """Call the underlying engine pure function. Subclass implements."""
```

Key design decisions:
- `_run` (sync) not `_arun` — engine functions are CPU-bound pure functions, not async I/O. LangChain calls `_run` in a thread pool when invoked from async context.
- `ClassVar` for `source_attribution` and `engine_function_name` — these are class-level metadata, not per-instance Pydantic fields (avoids LangChain field conflicts).
- The output envelope `{status, result, source_attribution, engine_function}` gives downstream consumers (Guardrail in M2.6, LangGraph in M2.7) everything they need to verify the amount came from the engine.

## Section 2: Five Engine Skills

### File: `backend/skills/calculate_income_tax.py`

Wraps `engine.income_tax_summary`. This is the most complex Skill (W-2 + self-employment + capital gains + FEIE + state tax combined).

```python
"""Skill: calculate comprehensive income tax summary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.skills.base import TaxSkill
from engine import income_tax_summary


class IncomeTaxInput(BaseModel):
    """Input schema for income tax calculation."""

    tax_year: int = Field(default=2026, ge=2020, le=2030)
    filing_status: str = "single"
    # Earned income
    w2_wages: float = Field(default=0, ge=0)
    net_self_employment_profit: float = Field(default=0, ge=0)
    other_ordinary_income: float = Field(default=0, ge=0)
    # Capital gains
    long_term_capital_gain: float = Field(default=0, ge=0)
    short_term_capital_gain: float = Field(default=0, ge=0)
    # FEIE
    foreign_earned_income: float = Field(default=0, ge=0)
    days_abroad: int = Field(default=0, ge=0, le=366)
    # Deductions
    se_health_insurance: float = Field(default=0, ge=0)
    retirement_contributions: float = Field(default=0, ge=0)
    deduction: float | None = Field(default=None, ge=0)
    # QBI
    qbi_w2_wages: float = Field(default=0, ge=0)
    qbi_ubia: float = Field(default=0, ge=0)
    is_sstb: bool = False
    # State
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    # MAGI override
    modified_agi: float | None = Field(default=None, ge=0)


class CalculateIncomeTax(TaxSkill):
    name: str = "calculate_income_tax"
    description: str = (
        "Calculate comprehensive income tax including federal, FICA, "
        "self-employment, state, FEIE, NIIT, and QBI deduction."
    )
    args_schema: type[BaseModel] = IncomeTaxInput
    source_attribution = "Rev. Proc. 2024-40 / IRS FICA / State DOR / Section 199A"
    engine_function_name = "income_tax_summary"

    def _execute_engine(self, params: dict[str, Any]) -> dict[str, Any]:
        return income_tax_summary(**params)
```

### File: `backend/skills/assess_feie.py`

Wraps `engine.feie_estimate`.

```python
class FeieInput(BaseModel):
    tax_year: int = Field(default=2026, ge=2020, le=2030)
    foreign_earned_income: float = Field(ge=0)
    days_abroad: int = Field(ge=0, le=366)


class AssessFeie(TaxSkill):
    name: str = "assess_feie"
    description: str = "Assess Foreign Earned Income Exclusion eligibility and calculate excluded amount."
    args_schema: type[BaseModel] = FeieInput
    source_attribution = "IRS Form 2555 / Section 911"
    engine_function_name = "feie_estimate"

    def _execute_engine(self, params):
        return feie_estimate(**params)
```

### File: `backend/skills/analyze_rsu.py`

Wraps `engine.rsu_tax_estimate`. Note the field name mapping: the Skill uses `fmv_per_share` but the engine expects `fair_market_value_per_share` (same mapping as `backend/routes/calc.py` line 115).

### File: `backend/skills/track_crypto.py`

Wraps `engine.crypto_gain_estimate`. Normalizes `method` to uppercase (same as `backend/routes/calc.py` line 109).

### File: `backend/skills/detect_nexus.py`

Wraps `engine.nexus_estimate`.

## Section 3: Skill Registry

### File: `backend/skills/registry.py`

Central registry that discovers and holds all Skill instances. Provides `get_skill(name)` and `get_all_skills()` for route handlers and future LangGraph integration.

```python
"""Skill registry — single source of truth for all available tax skills."""

from __future__ import annotations

from backend.skills.assess_feie import AssessFeie
from backend.skills.analyze_rsu import AnalyzeRsu
from backend.skills.calculate_income_tax import CalculateIncomeTax
from backend.skills.detect_nexus import DetectNexus
from backend.skills.track_crypto import TrackCrypto

_SKILLS: dict[str, object] = {}


def _register_defaults() -> None:
    for cls in (CalculateIncomeTax, AssessFeie, AnalyzeRsu, TrackCrypto, DetectNexus):
        instance = cls()
        _SKILLS[instance.name] = instance


def get_skill(name: str):
    """Return a Skill by name, or None if not found."""
    if not _SKILLS:
        _register_defaults()
    return _SKILLS.get(name)


def get_all_skills() -> list:
    """Return all registered Skills."""
    if not _SKILLS:
        _register_defaults()
    return list(_SKILLS.values())


def get_all_tools() -> list:
    """Return all Skills as LangChain Tools (for LangGraph integration)."""
    return get_all_skills()
```

Lazy initialization: `_register_defaults()` runs on first access, not at import time. This avoids import-order issues and keeps the module testable.

## Section 4: Skill Routes

### File: `backend/skills/routes.py`

Two endpoints on an APIRouter with prefix `/api/skills`.

```python
"""FastAPI routes for Skill discovery and invocation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.errors import error_response
from backend.skills.registry import get_all_skills, get_skill
from engine.rules_loader import RuleLoadError

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
def list_skills() -> dict[str, Any]:
    """List all available tax calculation skills with their schemas."""
    skills = get_all_skills()
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "input_schema": s.args_schema.model_json_schema() if s.args_schema else {},
            }
            for s in skills
        ],
        "total": len(skills),
    }


@router.post("/{skill_name}")
def invoke_skill(skill_name: str, request: Request, body: dict[str, Any]) -> Any:
    """Invoke a skill by name with the given input."""
    skill = get_skill(skill_name)
    if skill is None:
        request_id = str(getattr(request.state, "request_id", "unknown"))
        return JSONResponse(
            status_code=404,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="skill_not_found",
                message=f"Skill '{skill_name}' not found.",
                request_id=request_id,
            ),
        )
    try:
        result = skill.invoke(body)
        return result
    except RuleLoadError:
        request_id = str(getattr(request.state, "request_id", "unknown"))
        tax_year = body.get("tax_year", "requested")
        return JSONResponse(
            status_code=422,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="unsupported_tax_year",
                message=f"Tax year {tax_year} is not supported yet.",
                request_id=request_id,
            ),
        )
```

**Important**: Use `skill.invoke(body)` — this is LangChain's standard Tool invocation that handles `args_schema` validation automatically. If Pydantic validation fails, LangChain raises `ValidationError` which FastAPI's existing exception handler converts to 422.

## Section 5: Wire into main.py

In `create_app()`, import and include the skills router:

```python
from backend.skills.routes import router as skills_router
# ...
app.include_router(skills_router)
```

Place this after `app.include_router(profiles_router)`.

## Section 6: Package init

### File: `backend/skills/__init__.py`

Empty `__init__.py` to make this a Python package.

## Section 7: Tests

### File: `tests/test_m2_5_skills.py`

Use `unittest` with `unittest.mock.patch`. Tests are organized into 4 classes.

**TestSkillBase** (2 tests):
- `test_tax_skill_result_envelope`: Verify the output envelope structure has `status`, `result`, `source_attribution`, `engine_function` keys.
- `test_skill_is_langchain_tool`: Every registered Skill is an instance of `langchain_core.tools.BaseTool`.

**TestSkillRegistry** (3 tests):
- `test_registry_has_five_skills`: `get_all_skills()` returns exactly 5 skills.
- `test_registry_skill_names`: Names match `["calculate_income_tax", "assess_feie", "analyze_rsu", "track_crypto", "detect_nexus"]`.
- `test_get_skill_not_found`: `get_skill("nonexistent")` returns `None`.

**TestSkillExecution** (5 tests — one per Skill, mock the engine function):
- `test_calculate_income_tax_calls_engine`: Mock `income_tax_summary`, invoke Skill, verify engine was called with correct params and output is wrapped in envelope.
- `test_assess_feie_calls_engine`: Mock `feie_estimate`, invoke with `{foreign_earned_income: 120000, days_abroad: 335, tax_year: 2026}`, verify result.
- `test_analyze_rsu_calls_engine`: Mock `rsu_tax_estimate`, verify `fmv_per_share` → `fair_market_value_per_share` mapping.
- `test_track_crypto_calls_engine`: Mock `crypto_gain_estimate`, verify `method` normalized to uppercase.
- `test_detect_nexus_calls_engine`: Mock `nexus_estimate`, invoke and verify.

For each test: mock the engine function to return a known dict, invoke the Skill via `skill.invoke({...})`, assert:
1. Engine function was called once with expected kwargs
2. Return value has `status`, `result`, `source_attribution`, `engine_function` keys
3. `result` matches the mocked engine return value
4. `engine_function` matches the expected engine function name

**TestSkillRoutes** (6 tests — mock registry + engine):
- `test_list_skills_returns_200`: `GET /api/skills` → 200 with 5 skills, each has `name`, `description`, `input_schema`.
- `test_invoke_skill_returns_200`: `POST /api/skills/calculate_income_tax` with valid body → 200 with result envelope.
- `test_invoke_skill_not_found_returns_404`: `POST /api/skills/nonexistent` → 404 with `skill_not_found` code.
- `test_invoke_skill_invalid_input_returns_422`: `POST /api/skills/assess_feie` with missing required field → 422.
- `test_invoke_skill_unsupported_tax_year_returns_422`: Mock engine to raise `RuleLoadError` → 422 with `unsupported_tax_year`.
- `test_existing_calc_routes_unaffected`: `POST /calc/federal-income` still returns 200 (backward compatibility).

**TestSkillGracefulDegradation** (2 tests):
- `test_skills_work_without_pg`: With `ENABLE_POSTGRES=false`, `POST /api/skills/assess_feie` still works (Skills don't need PG).
- `test_calc_unaffected_by_skills`: Verify `/calc/federal-income` is completely independent of the Skills layer.

**Total: ~18 tests.**

Test setup pattern — follow the same pattern as `test_m2_4_profiles.py`:
```python
class TestSkillRoutes(unittest.TestCase):
    def setUp(self):
        from backend import config

        self._config_patchers = [
            patch.object(config, "ENABLE_POSTGRES", False),
            patch.object(config, "ENABLE_NEO4J", False),
            patch.object(config, "ENABLE_CHROMA", False),
        ]
        for patcher in self._config_patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.app = create_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)
```

## Section 8: Files Changed Summary

| File | Action | Purpose |
|---|---|---|
| `backend/skills/__init__.py` | **NEW** | Package init |
| `backend/skills/base.py` | **NEW** | TaxSkill base class (BaseTool subclass) |
| `backend/skills/calculate_income_tax.py` | **NEW** | Income tax summary Skill |
| `backend/skills/assess_feie.py` | **NEW** | FEIE assessment Skill |
| `backend/skills/analyze_rsu.py` | **NEW** | RSU tax analysis Skill |
| `backend/skills/track_crypto.py` | **NEW** | Crypto capital gains Skill |
| `backend/skills/detect_nexus.py` | **NEW** | Sales tax nexus detection Skill |
| `backend/skills/registry.py` | **NEW** | Skill registry (discovery + lookup) |
| `backend/skills/routes.py` | **NEW** | FastAPI routes for `/api/skills` |
| `backend/main.py` | **EDIT** | Include skills_router (2 lines) |
| `tests/test_m2_5_skills.py` | **NEW** | ~18 tests |

No changes to: `engine/`, `data/`, `backend/routes/calc.py`, `backend/knowledge/`, `backend/profiles/`, existing tests.

## Acceptance Gates

```powershell
# All existing + new tests pass
python -m unittest discover -s tests

# Lint clean
python -m ruff check engine backend tests

# No trailing whitespace / merge conflicts
git diff --check
```

Additional verification:
- `GET /api/skills` → 200 with 5 skills listed
- `POST /api/skills/calculate_income_tax` with `{"w2_wages": 120000, "filing_status": "single", "state_code": "CA", "tax_year": 2026}` → 200 with full tax breakdown
- `POST /api/skills/assess_feie` with `{"foreign_earned_income": 120000, "days_abroad": 335}` → 200 with FEIE result
- `POST /api/skills/nonexistent` → 404
- `POST /api/skills/assess_feie` with `{}` (missing required field) → 422
- All existing `/calc/*`, `/api/knowledge/search`, `/api/profiles` endpoints unaffected
- `GET /api/health` still returns store status
- All stores disabled → Skills still work (they don't use any DB)

## Commit Format

```
feat(skills): add LangChain Skill framework with 5 engine skills (M2.5)

Wrap income_tax_summary, feie_estimate, rsu_tax_estimate,
crypto_gain_estimate, and nexus_estimate as LangChain BaseTool
subclasses. Skill registry provides programmatic discovery.
REST endpoints: GET /api/skills (list) + POST /api/skills/{name} (invoke).
~18 tests covering base class, registry, execution, routes, degradation.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
