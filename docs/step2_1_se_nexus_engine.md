# Step 2.1 Self-Employment and Nexus Engine

Date: 2026-06-02

## Purpose

Add two data-ready pure engine functions before moving to broader golden-test infrastructure:

- `self_employment_tax`
- `nexus_estimate`

This step keeps the engine JSON-backed and does not add FastAPI routes or frontend integration.

## Completed Work

- Added `comparison` to effective nexus thresholds in `data/tax_years/2025/us_nexus.json`.
  - CA / NY / FL use `gt`.
  - TX uses `gte`.
  - WA remains `source_pending` and has no comparison.
- Added `load_nexus_rules` to `engine/rules_loader.py`.
- Added exports in `engine/__init__.py`.
- Implemented `self_employment_tax` using Decimal arithmetic.
- Implemented `nexus_estimate` with:
  - unknown-state blocking
  - `source_pending` blocking
  - CA/FL/TX amount-only thresholds
  - NY amount-and-transaction dual condition
  - 80% approaching detection
- Added golden fixtures:
  - `tests/golden/self_employment_tax.json`
  - `tests/golden/nexus_estimate.json`
- Extended `tests/test_engine.py`.
- Extended `tests/validate_step1_data.ps1` to require nexus `comparison` on effective thresholds.

## Guardrails

- No network calls.
- No reads from `index.html`.
- No naked tax rates or nexus thresholds in engine code.
- New functions reuse `_response` / `_not_covered`.
- `self_employment_tax` uses `Decimal` for rate math before display rounding.
- WA and unknown states return `not_covered` in nexus estimates.

## Validation Commands

```powershell
& "C:\Users\shawx\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest tests.test_engine -v
powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1
git diff --check
Get-FileHash -Algorithm SHA256 -LiteralPath index.html, frontend\index.html
```

## Validation Results

- `tests.test_engine`: 16 tests passed.
- Step 1 data validation passed.
- `git diff --check`: passed.
- Root `index.html` and `frontend/index.html` hashes still match.

## Known Limits

- Golden fixture runner remains deferred to M3.
- No FastAPI routes yet.
- No frontend integration yet.
- No RSU, crypto, or combined income summary function yet.
- Self-employment MVP assumes no other W-2 Medicare wages reduce Additional Medicare thresholds.

## Claude Review Focus

- Whether `self_employment_tax` uses Decimal correctly and matches golden cents.
- Whether `nexus_estimate` implements NY's dual condition correctly.
- Whether `comparison` values match source language intent.
- Whether WA and unknown states correctly return `not_covered`.
- Whether new code remains pure and JSON-backed.
