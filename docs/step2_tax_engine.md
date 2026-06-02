# Step 2 Tax Engine

Date: 2026-06-02

## Purpose

Create the first pure Python tax engine backed only by stored 2025 rule JSON.

This step turns the Step 1 data layer into callable functions for future API routes, alerts, and Copilot tool calls. It does not change the frontend and does not expose FastAPI endpoints yet.

## Completed Work

- Added the `engine` Python package.
- Added a rule loader that reads only local JSON files under `data/tax_years/<year>/`.
- Implemented pure functions:
  - `bracket_tax`
  - `federal_income_tax`
  - `fica_tax`
  - `feie_estimate`
  - `state_income_tax`
- Added standard-library unit tests in `tests/test_engine.py`.
- Removed the placeholder `engine/.gitkeep`.
- Hardened the rule loader and response shape after review:
  - cached rule dictionaries are returned as isolated deep copies
  - `ok` and `not_covered` responses now share the same top-level keys
  - `reason` is present for every response and is `null` for successful calculations
  - FICA assumptions now distinguish annual taxpayer liability thresholds from payroll withholding timing

## Guardrails

- The engine does not fetch live web pages.
- The engine does not read from `index.html`.
- The engine does not fall back to prototype hardcoded values.
- Callers cannot mutate cached rule dictionaries and poison later calculations.
- `state_income_tax` returns `status: not_covered` for:
  - `pending_extraction`
  - `source_pending`
  - unknown states
- CA and NY are blocked until bracket extraction is implemented.
- MA and TX are blocked until official income-tax source ingestion is completed.

## Acceptance Criteria

- Federal tax uses 2025 JSON brackets and standard deduction.
- FICA uses 2025 JSON Social Security wage base, Medicare rate, and Additional Medicare filing-status thresholds.
- FEIE uses 2025 JSON maximum exclusion and 330-day physical presence threshold.
- Effective flat/zero-tax states calculate from JSON.
- Pending or source-pending state rules explicitly refuse calculation.
- All engine responses include the same top-level keys.
- Mutating a loaded rule copy does not affect later engine calculations.
- Existing Step 1 data validation still passes.
- Prototype files remain byte-identical.

## Validation Commands

```powershell
& "C:\Users\shawx\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest tests.test_engine -v
powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1
git diff --check
Get-FileHash -Algorithm SHA256 -LiteralPath index.html, frontend\index.html
```

## Validation Results

- `tests.test_engine`: 13 tests passed.
- `validate_step1_data.ps1`: passed.
- `git diff --check`: passed.
- Root `index.html` and `frontend/index.html` hashes still match.

## Known Limits

- No FastAPI routes yet.
- No frontend integration yet.
- No combined income summary function yet.
- No RSU, self-employment, crypto, or nexus calculation functions yet.
- CA/NY bracket extraction remains pending.
- MA/TX state income tax remains source-pending.
- The engine currently returns dicts. A typed schema can be added when API contracts are introduced.

## Claude Review Focus

- Whether the engine is pure and only reads stored JSON rules.
- Whether `state_income_tax` correctly blocks pending/source-pending states.
- Whether result shapes are consistent enough for the future FastAPI layer.
- Whether cached rule data is protected from caller mutation.
- Whether tests cover both successful calculations and guardrail failures.
- Whether any prototype hardcoded values leaked into the engine.
