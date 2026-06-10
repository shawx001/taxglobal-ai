# Codex Prompt: M3.4 — Fact-checker Guardrail

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `docs/m3_step_plan.md` (M3.4 section) → `backend/orchestrator/response.py` → `backend/orchestrator/nodes.py` (`_attach_llm_answer_text`) → `backend/guardrail/middleware.py` → `engine/money.py`

## Task

Add a fact-checker guardrail that verifies the M3.3 LLM-generated `answer_text` did not tamper with engine numbers before it reaches the user. Every dollar amount in the LLM text must match an amount in the structured engine answer **to the cent**. Tampering → the text is dropped and the M2 template response is kept. This is the last gate before `ENABLE_LLM` can ever be turned on in production (see the NOTE in `backend/orchestrator/response.py`).

**Why:** LLM = ears + mouth, never brain. M3.3 deliberately attached `answer_text` WITHOUT verification and documented that M3.4 must land before production use. Acceptance criterion from `m3_step_plan.md`: "Fact-checker 拦截 100% 的金额篡改（引擎说 $24,734 LLM 说 $24,700 → 拦截）".

## Architecture Decision (IMPORTANT — READ THIS)

**Numeric comparison MUST be Decimal-normalized, never string match.** PR #69 review finding: the engine's `_money()` returns floats quantized to cents, so the answer dict carries `13200.0`, while a correct LLM reply writes `$13,200.00`. String comparison would false-positive on every formatted amount. Strip `$`, commas, and whitespace. Engine side: `Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` — same rounding as `engine/money.py`; quantize without an explicit mode defaults to ROUND_HALF_EVEN and drifts from the engine. Text side: convert EXACTLY as written with NO rounding — rounding the text side would let sub-cent tampering like `$24,734.005` collapse onto the engine's `24734.00` and PASS. Decimal equality/hashing are numeric (`Decimal("24734") == Decimal("24734.00")`), so exact text values still match the quantized engine set.

**Shaw has approved external LLM calls with PII sanitization (2026-06-08). Do NOT add any new external-API guards.** This step makes NO LLM calls at all — it is a pure local validation function.

**Never log LLM output or user content.** Established across PR #67/#69: log only generic codes / model names / counts. Issue strings returned to the caller may name the failed check but must not quote the LLM text.

## Core Constraints

1. **Pure function, no I/O**: `check_response_fidelity()` is deterministic, stateless, makes no network/database calls.
2. **`ENABLE_LLM=false` → zero change**: the checker is only invoked from `_attach_llm_answer_text`, which already early-returns when the flag is off. Existing tests must pass unchanged.
3. **BLOCK fails closed**: on BLOCK the response simply has no `answer_text` — identical shape to "LLM unavailable". The user never sees an error.
4. **All money math in `Decimal`** — no float arithmetic anywhere in the checker.
5. **Keep `backend/guardrail/middleware.py` and `validator-`related code untouched** — they guard the engine path (skill_output). The fact-checker guards the LLM path (`answer_text`) and lives in its own module. (This deviates from the step plan's "validator.py 修改" — intentional: `answer_text` is created in `format_node`, so the check belongs there.)
6. Module size < 200 lines excluding tests.

## File 1: `backend/guardrail/fact_checker.py` — NEW

```python
"""M3.4: fact-checker guardrail for LLM-generated answer text.

Verifies that every dollar amount in the LLM's natural-language answer
matches an amount present in the structured engine answer, to the cent.
Pure local validation — no LLM calls, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

VERDICT_PASS = "pass"
VERDICT_WARN = "warn"
VERDICT_BLOCK = "block"

_CENT = Decimal("0.01")

# $-prefixed amounts in LLM text: $24,734.00 / $ 13,200 / $0.50
_DOLLAR_AMOUNT_PATTERN = re.compile(r"\$\s*([0-9][\d,]*(?:\.\d+)?)")

# Out-of-scope advice (product principle: no investment/financial advice)
_ADVICE_PATTERNS = (
    "投资", "理财", "买保险", "开公司", "炒股",
    "invest", "buy insurance", "financial advis",
)

# Absolute claims (compliance: never promise outcomes)
_ABSOLUTE_PATTERNS = ("保证", "一定能", "肯定能", "guarantee", "definitely will")


@dataclass(frozen=True)
class FactCheckResult:
    verdict: str  # pass / warn / block
    issues: list[str] = field(default_factory=list)


def _extract_dollar_amounts(text: str) -> list[Decimal]:
    amounts: list[Decimal] = []
    for match in _DOLLAR_AMOUNT_PATTERN.finditer(text):
        raw = match.group(1).replace(",", "")
        try:
            amounts.append(Decimal(raw).quantize(_CENT))
        except InvalidOperation:
            continue
    return amounts


def _collect_engine_numbers(value: Any, out: set[Decimal]) -> None:
    """Recursively collect every numeric leaf of the engine answer.

    Engine amounts are floats quantized to cents (engine/money.py), but the
    answer dict also contains strings and ints; accept any value that
    converts cleanly to Decimal. Known v1 limitation: non-money numerics
    (tax_year, days) also land in the set, so an LLM amount equal to one of
    them would pass — acceptable, documented here.
    """
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        try:
            out.add(Decimal(str(value)).quantize(_CENT))
        except InvalidOperation:
            pass
        return
    if isinstance(value, str):
        try:
            out.add(Decimal(value.replace(",", "")).quantize(_CENT))
        except InvalidOperation:
            pass
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_engine_numbers(item, out)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_engine_numbers(item, out)


def check_response_fidelity(
    answer_text: str,
    answer: dict[str, Any],
    sources: list[str],
) -> FactCheckResult:
    """Validate LLM answer text against the structured engine answer.

    BLOCK: any $-amount in the text that is not present (to the cent) in
    the engine answer — covers both tampering and hallucinated amounts.
    WARN: out-of-scope advice, absolute claims, or no source mentioned.
    """
    issues: list[str] = []

    engine_numbers: set[Decimal] = set()
    _collect_engine_numbers(answer, engine_numbers)

    for amount in _extract_dollar_amounts(answer_text):
        if amount not in engine_numbers:
            # Do not include the amount or any LLM text in the issue string.
            return FactCheckResult(
                verdict=VERDICT_BLOCK,
                issues=["llm_amount_not_in_engine_output"],
            )

    text_lower = answer_text.lower()
    if any(pattern in text_lower for pattern in _ADVICE_PATTERNS):
        issues.append("out_of_scope_advice")
    if any(pattern in text_lower for pattern in _ABSOLUTE_PATTERNS):
        issues.append("absolute_claim")
    if sources and not any(str(source) in answer_text for source in sources):
        issues.append("no_source_cited")

    if issues:
        return FactCheckResult(verdict=VERDICT_WARN, issues=issues)
    return FactCheckResult(verdict=VERDICT_PASS)
```

Adjust internals as needed, but keep: the public names (`FactCheckResult`, `check_response_fidelity`, `VERDICT_*`), Decimal-only comparison, fail-closed BLOCK on the first unmatched amount, and no LLM text in issue strings.

## File 2: `backend/orchestrator/nodes.py` — MODIFY `_attach_llm_answer_text()` ONLY

```python
def _attach_llm_answer_text(response: dict[str, Any], query: str) -> dict[str, Any]:
    """M3.3: add a natural-language ``answer_text`` when the LLM is enabled.

    The structured ``answer`` is never modified. M3.4: the text must pass
    the fact-checker; BLOCK means the template response is kept unchanged.
    """

    from backend import config

    if not config.ENABLE_LLM:
        return response

    from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity
    from backend.orchestrator.response import llm_format_response

    text = llm_format_response(query, response.get("answer", {}), response.get("sources", []))
    if text is None:
        return response

    fact_check = check_response_fidelity(text, response.get("answer", {}), response.get("sources", []))
    if fact_check.verdict == VERDICT_BLOCK:
        # Fail closed: drop the LLM text, keep the M2 template response.
        # Generic log only — never the text or amounts.
        logger.warning("fact-checker blocked LLM answer_text: %s", ",".join(fact_check.issues))
        return response

    response["answer_text"] = text
    response["fact_check"] = {"verdict": fact_check.verdict, "issues": fact_check.issues}
    return response
```

Note: `nodes.py` currently has no module logger — add `logger = logging.getLogger("taxglobal.orchestrator")` + `import logging` at the top of `nodes.py` (top-level imports there are fine; only `intent.py` has the byte-identical-M2-section constraint).

## File 3: `docs/m3_step_plan.md` — status updates only

- M3.3 status → `✅ 已合并（PR #69，2026-06-10）`（保留现有实现说明，追加：sanitizer 9 位金额掩码缺陷已在该 PR 一并修复）
- M3.4 status → `✅ 已合并（PR #XX）`（merge 后由 review 流程确认；提 PR 时先写 🚧）
- 步骤总览表同步 M3.3 ✅ / M3.4 状态

## Tests: `tests/test_m3_4_fact_checker.py`

Cover at minimum (exact amounts matter — independent of the example code):

```python
# --- unit: check_response_fidelity ---
# PASS: text "联邦税 $24,734.00" + answer {"data": {"total_tax": 24734.0}} → pass
# BLOCK tampered: text "$24,700.00" + engine 24734.0 → block, issues=["llm_amount_not_in_engine_output"]
# BLOCK hallucinated: text mentions "$1,000.00" but engine has only 24734.0 → block
# PASS formatted: engine float 13200.0 ↔ text "$13,200.00"（千分位 + 两位小数）
# PASS no-cents: text "$24,734" ↔ engine 24734.0（quantize 后相等）
# PASS string engine values: answer {"data": {"total_tax": "24734.00"}}（字符串金额也收集）
# PASS no amounts in text: knowledge 回答无 $ 金额 → pass（来源已引用时）
# WARN advice: text 含 "建议你投资..." → warn, issues 含 "out_of_scope_advice"
# WARN absolute: text 含 "保证退税" → warn, issues 含 "absolute_claim"
# WARN no source: sources=["IRS Rev. Proc. 2024-40"] 但 text 未提及 → warn
# WARN 不叠加成 BLOCK：advice + 金额正确 → verdict 仍是 warn
# bool 不被当作数字：answer 含 True 时 "$1.00" 仍 block

# --- integration: format_node (复用 tests/test_m3_3_response.py 的 fixture 写法) ---
# ENABLE_LLM=true + mock 返回正确金额文本 → answer_text 存在 + fact_check.verdict == "pass"
# ENABLE_LLM=true + mock 返回篡改金额 "$99,999.00" → response 无 answer_text（被拦截）
# ENABLE_LLM=false → response 无 answer_text 也无 fact_check（M2 schema 不变）
# WARN 路径：answer_text 保留 + fact_check.issues 非空
```

Follow the established test patterns: `@patch("backend.llm.client.get_provider")` for provider mocking, `cfg.ENABLE_LLM` mutation with try/finally for the flag (see `tests/test_m3_3_response.py`).

## Adversarial self-review BEFORE opening the PR (mandatory)

Run the full malformed-input checklist in one pass — do not let review rounds drip-find holes:
- `answer_text` empty / no `$` / `$` followed by garbage (`$abc`, `$.`, `$1,2,3`) → no crash, regex skips or InvalidOperation caught
- `answer` dict containing None / bool / nested lists / non-numeric strings → collector skips cleanly
- amounts with/without cents, with/without commas, `$ 24,734.00`（$ 后带空格）→ all normalize identically
- issue strings and log lines contain ZERO LLM text and ZERO amounts
- `sources` containing non-str values → `str(source)` coercion, no crash

## Acceptance Gates

```powershell
python -m unittest discover -s tests
python -m unittest tests.test_m3_4_fact_checker -v
python -m ruff check engine backend tests
git diff --check
```

Plus: all 463 pre-existing tests pass unchanged (ENABLE_LLM=false 路径零行为变化).

## Commit Format

```
feat(guardrail): add M3.4 fact-checker for LLM answer text

Verify every dollar amount in the LLM-generated answer_text against the
structured engine answer with cent-exact Decimal comparison. Tampered or
hallucinated amounts fail closed: the text is dropped and the M2 template
response is kept. Out-of-scope advice, absolute claims, and missing source
citations downgrade to WARN annotations.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

## Notes for Codex

- **DO NOT call any LLM** — this is pure local validation.
- **DO NOT modify** `backend/orchestrator/response.py`, `backend/orchestrator/intent.py`, `backend/guardrail/middleware.py`, `graph.py`, `state.py`.
- **DO NOT log** LLM text, extracted amounts, or user content — generic issue codes only.
- **DO NOT use float arithmetic** — every comparison goes through `Decimal(...).quantize(Decimal("0.01"))`.
- **DO NOT add external-API guards** — no network involved, and external LLM calls are already approved at the provider layer.
- BLOCK on the FIRST unmatched amount (fail fast, fail closed). WARN issues accumulate.
- `fact_check` is a NEW response field next to `answer_text` — only present when `answer_text` is attached; M2 schema (flag off) unchanged.
- Commit this prompt file (`docs/codex_prompts/m3_4_fact_checker.md`) in the PR as well.
