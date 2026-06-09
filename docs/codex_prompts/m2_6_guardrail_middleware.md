# Codex Prompt: M2.6 Guardrail Middleware

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `docs/m2_step_plan.md` section M2.6 → `docs/agent_architecture_principles.md` (§2 Guardrail)

## Task

Build a guardrail validation layer that enforces the project's core invariant: **all monetary amounts in responses MUST originate from the rule engine — LLM / external sources are untrusted**. This is the "规则引擎是唯一真相, LLM 输出当不可信" principle from `agent_architecture_principles.md` §2.

The guardrail intercepts every Skill output after the engine call returns and before the response is sent to the user. It validates structural integrity (envelope shape, known engine function), semantic integrity (`not_covered` cannot be overridden with fabricated amounts), and provides cross-validation utilities that the M2.7 LangGraph Workflow will use to verify LLM-generated text doesn't contain amounts that differ from the engine result.

Additionally, implement an escalation framework with four severity levels. When a guardrail check fails, the system logs a structured audit event (to the Python logger for now; M2.9 will add PostgreSQL persistence) and either blocks the response or flags it for human review.

Existing `/calc/*`, `/api/skills`, `/api/knowledge/search`, `/api/profiles` endpoints must continue to work. The guardrail wraps Skill output only — it does NOT touch the existing `/calc/*` routes.

## Core Constraints

1. **Backward compatibility**: All ~210 existing tests and all existing routes must pass unchanged. Engine module `engine/` is read-only.
2. **No new dependencies**: Use only stdlib + pydantic + fastapi (already installed). No new pip packages.
3. **Engine is the only truth**: The guardrail validates that amounts come from the engine. It does NOT compute any tax amount itself.
4. **Pure functions, stateless**: Validator and escalation functions are pure — no shared mutable state, no database writes (M2.6 logs to stdlib `logging`; PG audit comes in M2.9).
5. **Graceful degradation**: Guardrail does NOT depend on any database (PG, Neo4j, Chroma). All checks use in-memory validation against the Skill output envelope and engine output structure.
6. **Data sovereignty**: No external API calls. All validation is local.
7. **PII safety**: Guardrail audit logs MUST NOT contain income amounts, SSN, or any PII. Log only: `event`, `severity`, `reason`, `request_id`, `engine_function`, `check_code`. Never log the `result` dict or input data.

## Section 1: Escalation Framework

### File: `backend/guardrail/__init__.py`

Empty `__init__.py` to make this a Python package.

### File: `backend/guardrail/escalation.py`

Define the escalation severity levels and the structured audit logging function.

```python
"""Guardrail escalation levels and audit logging."""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("taxglobal.guardrail")


class EscalationLevel(str, Enum):
    """Guardrail check severity. Higher = more serious."""

    INFO = "info"               # Passed; informational annotation
    WARNING = "warning"         # Minor issue; allow but log
    NEEDS_REVIEW = "needs_review"  # Flag for human review; response tagged
    BLOCKED = "blocked"         # Hard block; response suppressed


class CheckResult(BaseModel):
    """Single guardrail check outcome."""

    passed: bool
    code: str
    message: str = ""


class GuardrailVerdict(BaseModel):
    """Aggregate result of all guardrail checks on one Skill output."""

    level: EscalationLevel
    checks: list[CheckResult]
    reason: str = ""


def request_human_review(
    *,
    reason: str,
    severity: EscalationLevel,
    request_id: str = "",
    engine_function: str = "",
    check_code: str = "",
) -> dict[str, Any]:
    """Log a structured guardrail escalation event and return an escalation marker.

    M2.6: writes to Python structured logger (no PII).
    M2.9: will additionally write to audit_log table in PostgreSQL.
    """
    logger.warning(
        json.dumps(
            {
                "event": "guardrail_escalation",
                "severity": severity.value,
                "reason": reason,
                "request_id": request_id,
                "engine_function": engine_function,
                "check_code": check_code,
            },
            separators=(",", ":"),
        )
    )
    return {
        "escalation_level": severity.value,
        "reason": reason,
        "request_id": request_id,
    }
```

Key decisions:
- `EscalationLevel` is a `str, Enum` so it serializes cleanly to JSON.
- `request_human_review` logs structured JSON (same pattern as `backend/main.py` line 118). **No PII fields** — only event metadata.
- Returns a plain dict marker that can be embedded in responses or stored for M2.9 audit.

## Section 2: Validators

### File: `backend/guardrail/validator.py`

Pure validation functions. Each check returns a `CheckResult`; `validate_skill_output` aggregates them into a `GuardrailVerdict`.

```python
"""Pure validation functions for Skill output guardrail checks."""

from __future__ import annotations

import re
from typing import Any

from backend.guardrail.escalation import CheckResult, EscalationLevel, GuardrailVerdict

# Whitelist of known engine functions that Skills can legitimately call.
# Update this set when adding new Skills in future steps.
KNOWN_ENGINE_FUNCTIONS: frozenset[str] = frozenset(
    {
        "income_tax_summary",
        "feie_estimate",
        "rsu_tax_estimate",
        "crypto_gain_estimate",
        "nexus_estimate",
    }
)

# Pattern matching engine monetary output format: "-123.45" or "0.00"
_MONEY_PATTERN = re.compile(r"^-?\d+\.\d{2}$")


def validate_skill_output(skill_output: dict[str, Any]) -> GuardrailVerdict:
    """Run all guardrail checks on a Skill output envelope.

    The envelope shape (from TaxSkillResult) is:
        {status, result, source_attribution, engine_function}
    where `result` is the full engine response dict:
        {status, input, result, breakdown, rule_version, citations, assumptions, reason}
    """
    checks = [
        _check_envelope_structure(skill_output),
        _check_engine_function_known(skill_output),
        _check_not_covered_integrity(skill_output),
    ]
    # Determine worst severity
    if any(not c.passed for c in checks):
        failed = [c for c in checks if not c.passed]
        return GuardrailVerdict(
            level=EscalationLevel.BLOCKED,
            checks=checks,
            reason="; ".join(c.message for c in failed),
        )
    return GuardrailVerdict(
        level=EscalationLevel.INFO,
        checks=checks,
        reason="All checks passed.",
    )
```

Individual check functions (implement all of these):

**`_check_envelope_structure(output)`**: Verify `output` has all four required keys: `status`, `result`, `source_attribution`, `engine_function`. Missing any → BLOCKED.

**`_check_engine_function_known(output)`**: Verify `output["engine_function"]` is in `KNOWN_ENGINE_FUNCTIONS`. Unknown → BLOCKED. This prevents fabricated Skill results claiming to come from a non-existent engine function.

**`_check_not_covered_integrity(output)`**: If `output["status"] == "not_covered"`, verify that `output["result"]["result"]` is `None`. The engine's `_not_covered()` helper (see `engine/responses.py` line 38) always sets `result=None`. If someone constructs a fake `not_covered` response with amounts, this catches it.

**`extract_engine_amounts(engine_output) -> dict[str, str]`**: Walk the engine output dict and extract all monetary string values (matching `_MONEY_PATTERN`). Extract from both `engine_output["result"]` (the computed values) and `engine_output["breakdown"]` (the line items). Return a flat dict like `{"total_tax": "12345.67", "breakdown.federal_tax": "4567.89"}`. This creates the **reference set** that M2.7 LangGraph will use for cross-validation.

**`validate_amounts_match(claimed: dict[str, str], engine_amounts: dict[str, str]) -> GuardrailVerdict`**: For M2.7+ cross-validation. Check that every amount in `claimed` exists somewhere in `engine_amounts` values. Any mismatch → BLOCKED with details of which fields don't match. This is the function that prevents an LLM from inserting fabricated dollar amounts into a response.

**`check_coverage(topic: str, state_code: str | None = None, tax_year: int = 2026) -> CheckResult`**: Check whether the engine covers a given topic/jurisdiction. Uses a `TOPIC_SKILL_MAP` dict mapping topic strings (e.g. `"income_tax"`, `"feie"`, `"rsu"`, `"crypto"`, `"nexus"`) to skill names. Unknown topic → not covered. If `state_code` is provided, attempt to load state data via `engine.rules_loader.load_rule_file(tax_year, "us_states.json")` and verify the state code exists. Wrap `RuleLoadError` → not covered. This function is used by M2.7 to route queries: covered topics go to Skills; uncovered topics go to KB-only response or escalation.

## Section 3: Middleware Integration

### File: `backend/guardrail/middleware.py`

The middleware function that `backend/skills/routes.py` calls after Skill invocation.

```python
"""Guardrail middleware for post-processing Skill output."""

from __future__ import annotations

from typing import Any

from backend.guardrail.escalation import EscalationLevel, request_human_review
from backend.guardrail.validator import validate_skill_output


class GuardrailViolation(Exception):
    """Raised when guardrail blocks a Skill output."""

    def __init__(self, escalation: dict[str, Any]) -> None:
        self.escalation = escalation
        super().__init__(escalation.get("reason", "Guardrail violation"))


def guardrail_check(
    skill_output: dict[str, Any],
    request_id: str = "",
) -> dict[str, Any]:
    """Validate a Skill output through all guardrail checks.

    Returns the original output (possibly annotated with _guardrail metadata)
    if validation passes. Raises GuardrailViolation if blocked.
    """
    verdict = validate_skill_output(skill_output)
    engine_fn = skill_output.get("engine_function", "")

    if verdict.level == EscalationLevel.BLOCKED:
        escalation = request_human_review(
            reason=verdict.reason,
            severity=EscalationLevel.BLOCKED,
            request_id=request_id,
            engine_function=engine_fn,
            check_code=",".join(c.code for c in verdict.checks if not c.passed),
        )
        raise GuardrailViolation(escalation)

    if verdict.level == EscalationLevel.NEEDS_REVIEW:
        request_human_review(
            reason=verdict.reason,
            severity=EscalationLevel.NEEDS_REVIEW,
            request_id=request_id,
            engine_function=engine_fn,
            check_code=",".join(c.code for c in verdict.checks if not c.passed),
        )
        skill_output["_guardrail"] = {
            "needs_review": True,
            "reason": verdict.reason,
        }

    return skill_output
```

### File: `backend/skills/routes.py` (EDIT)

Add guardrail validation to the `invoke_skill` endpoint. After `result = skill.invoke(body)` and the `invalid_input` status check, add `guardrail_check(result, request_id)`. Handle `GuardrailViolation` in the try/except chain.

The new exception handler:
```python
from backend.guardrail.middleware import GuardrailViolation, guardrail_check

# Inside invoke_skill, after the invalid_input check:
result = guardrail_check(result, request_id)
return result

# New except clause (add between RuleLoadError and ValidationError handlers):
except GuardrailViolation as exc:
    return JSONResponse(
        status_code=422,
        headers={"X-Request-ID": request_id},
        content=error_response(
            code="guardrail_blocked",
            message=exc.escalation.get("reason", "Output blocked by guardrail."),
            request_id=request_id,
        ),
    )
```

**Important**: The guardrail check runs AFTER the engine call succeeds. It does NOT interfere with input validation, `RuleLoadError`, or other early-exit paths. Place the `guardrail_check` call right before `return result` in the success path.

## Section 4: Tests

### File: `tests/test_m2_6_guardrail.py`

Use `unittest` + `unittest.mock.patch`. Organize into test classes.

**TestCheckResult and TestEscalationLevel** (2-3 tests):
- `test_escalation_levels_are_ordered`: Verify the four levels serialize to expected strings.
- `test_check_result_model`: Verify `CheckResult` accepts `passed`, `code`, `message`.

**TestValidator** (6-8 tests):
- `test_valid_skill_output_passes`: Construct a valid Skill output envelope (matching the `TaxSkillResult` format with a known `engine_function`, `status="ok"`, engine result with amounts) → `validate_skill_output` returns `level=INFO`.
- `test_unknown_engine_function_blocked`: Set `engine_function` to `"fake_function"` → BLOCKED.
- `test_missing_envelope_field_blocked`: Remove `source_attribution` from envelope → BLOCKED.
- `test_not_covered_with_null_result_passes`: Envelope with `status="not_covered"` and `result.result=None` → passes.
- `test_not_covered_with_amounts_blocked`: Envelope with `status="not_covered"` but `result.result={"total_tax": "100.00"}` → BLOCKED.
- `test_extract_engine_amounts`: Call `extract_engine_amounts` on a real-shaped engine output dict (see `engine/feie.py` for the shape: `result` dict with `_money()` formatted values + `breakdown` list). Verify the returned dict contains all monetary fields from both `result` and `breakdown`.
- `test_validate_amounts_match_passes`: Engine amounts `{"total_tax": "500.00"}`, claimed `{"my_total": "500.00"}` → passes.
- `test_validate_amounts_match_detects_mismatch`: Engine amounts `{"total_tax": "500.00"}`, claimed `{"my_total": "999.99"}` → BLOCKED.

**TestCheckCoverage** (3 tests):
- `test_known_topic_covered`: `check_coverage("income_tax")` → passed.
- `test_unknown_topic_not_covered`: `check_coverage("yacht_tax")` → not covered.
- `test_state_coverage_check`: `check_coverage("income_tax", state_code="CA")` → covered; `check_coverage("income_tax", state_code="XX")` → not covered. (Mock `load_rule_file` if needed to avoid file dependency.)

**TestEscalation** (2 tests):
- `test_request_human_review_logs`: Mock `logging.getLogger("taxglobal.guardrail").warning`, call `request_human_review(reason="test", severity=BLOCKED, request_id="r1")`, verify the mock was called with a JSON string containing `"guardrail_escalation"` and `"blocked"`. Verify the returned dict has `escalation_level`, `reason`, `request_id`.
- `test_request_human_review_no_pii`: Call `request_human_review`, capture the logged JSON string, verify it does NOT contain amount-like patterns (`\d+\.\d{2}`) or known PII field names (`ssn`, `income`).

**TestGuardrailMiddleware** (3 tests):
- `test_guardrail_check_passes_valid_output`: Valid envelope → returns the same dict.
- `test_guardrail_check_raises_on_blocked`: Invalid envelope (unknown engine function) → raises `GuardrailViolation`.
- `test_guardrail_check_annotates_needs_review`: Construct an envelope that triggers `NEEDS_REVIEW` (you may need to add a check or adjust the verdict logic to produce this level — e.g., a warning-level check) → output gets `_guardrail.needs_review` annotation.

**TestGuardrailIntegration** (4 tests — use FastAPI TestClient, same setup pattern as `test_m2_5_skills.py`):
- `test_skill_invoke_with_guardrail_passes`: `POST /api/skills/assess_feie` with valid input → 200, result has engine amounts (guardrail passes transparently).
- `test_skill_invoke_guardrail_blocked`: Mock the Skill to return an output with `engine_function="fabricated"` → 422 with `guardrail_blocked` code.
- `test_existing_calc_routes_unaffected`: `POST /calc/federal-income` still returns 200 (guardrail is Skill-only).
- `test_existing_skill_list_unaffected`: `GET /api/skills` still returns 200 with 5 skills.

Test setup pattern — follow `test_m2_5_skills.py`:
```python
class TestGuardrailIntegration(unittest.TestCase):
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

**Total: ~18-20 tests.**

## Section 5: Files Changed Summary

| File | Action | Purpose |
|---|---|---|
| `backend/guardrail/__init__.py` | **NEW** | Package init |
| `backend/guardrail/escalation.py` | **NEW** | EscalationLevel enum + CheckResult/GuardrailVerdict models + `request_human_review()` |
| `backend/guardrail/validator.py` | **NEW** | Pure validation functions: `validate_skill_output`, `extract_engine_amounts`, `validate_amounts_match`, `check_coverage` |
| `backend/guardrail/middleware.py` | **NEW** | `guardrail_check()` wrapper + `GuardrailViolation` exception |
| `backend/skills/routes.py` | **EDIT** | Add `guardrail_check` call in `invoke_skill` + `GuardrailViolation` handler |
| `tests/test_m2_6_guardrail.py` | **NEW** | ~18-20 tests |

No changes to: `engine/`, `data/`, `backend/routes/calc.py`, `backend/knowledge/`, `backend/profiles/`, `backend/skills/base.py`, `backend/skills/registry.py`, `backend/main.py`, existing tests.

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
- `POST /api/skills/assess_feie` with `{"foreign_earned_income": 120000, "days_abroad": 335, "tax_year": 2026}` → 200 (guardrail passes transparently; engine amounts untouched)
- `POST /api/skills/calculate_income_tax` with `{"w2_wages": 120000, "filing_status": "single", "state_code": "CA", "tax_year": 2026}` → 200 (guardrail passes)
- All existing `/calc/*` endpoints unaffected (guardrail is Skill-only)
- `GET /api/skills` still lists 5 skills
- `GET /api/health` still returns store status
- All stores disabled → Skills + guardrail still work (no DB dependency)
- Guardrail audit logs written to `taxglobal.guardrail` logger with structured JSON (verify via mock in tests)
- No PII in any guardrail log output

## Commit Format

```
feat(guardrail): add guardrail validation middleware for Skill output (M2.6)

Validate Skill output amounts originate from the rule engine.
Checks: envelope structure, known engine function whitelist,
not_covered integrity. Escalation framework with 4 severity levels
(INFO/WARNING/NEEDS_REVIEW/BLOCKED). Cross-validation utilities
for M2.7 LangGraph LLM output. ~18-20 tests.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
