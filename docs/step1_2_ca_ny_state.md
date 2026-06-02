# Step 1.2 - CA/NY Progressive State Income Tax

## Purpose

Make California and New York state income tax calculable end to end using archived official rule data, without adding frontend or backend hardcoded tax rates.

## What Changed

- Changed CA and NY in `data/tax_years/2025/us_states.json` from `pending_extraction` to `effective`.
- Added CA and NY progressive brackets for all five filing statuses.
- Added explicit CA/NY assumptions for MVP limitations:
  - CA Mental Health Services Tax over $1,000,000 is not modeled.
  - NY tax benefit recapture above $107,650 NYAGI is not modeled.
- Updated `state_income_tax` to accept `filing_status`.
- Added a progressive-state branch that reads brackets from JSON and reuses `bracket_tax`.
- Updated FastAPI `StateIncomeRequest` so `/calc/state-income` accepts and passes `filing_status`.
- Updated the frontend personal income tax API call to pass the selected filing status to `/calc/state-income`.
- Updated golden tests and state validation guards.

## Acceptance Criteria

- CA/NY no longer return `not_covered` for supported 2025 state income tax inputs.
- Progressive state tax brackets are read from `us_states.json`, not hardcoded in engine/API/frontend.
- Flat and no-income-tax states keep existing behavior.
- MA/TX remain honest `not_covered` because their source status is still not ready.
- Root `index.html` remains frozen.

## Golden Values

- CA single taxable income $200,000 -> $15,038.64.
- CA married filing jointly taxable income $125,000 -> $4,768.10.
- NY single taxable income $100,000 -> $5,431.75.
- NY married filing jointly taxable income $100,000 -> $5,167.50.

## Browser/API Verification

- Restarted FastAPI at `http://127.0.0.1:8000`.
- Served `frontend/` locally at `http://127.0.0.1:5173`.
- Verified frontend personal income tax sends `filing_status` to `/calc/state-income`.
- Verified CA no longer shows `not_covered`; default demo taxable income $90,000 shows CA state tax $4,809 with `ca_2025_540_tax_rate_schedules`.
- Verified NY no longer shows `not_covered`; default demo taxable income $90,000 shows NY state tax $4,832 with `ny_2025_it201_instructions`.

## Files Changed

- `data/tax_years/2025/us_states.json`
- `engine/tax_engine.py`
- `backend/schemas.py`
- `frontend/index.html`
- `tests/validate_step1_data.ps1`
- `tests/golden/state_income_tax.json`
- `tests/test_engine.py`
- `tests/test_api_calc.py`
- `docs/feature_status.md`
- `docs/step1_2_design_ca_ny_state.md`
- `docs/step1_2_ca_ny_state.md`

## Known Limits

- CA 1% Mental Health Services Tax over $1,000,000 is not modeled in this MVP estimate.
- NY tax benefit recapture above $107,650 NYAGI is not modeled, so high-income NY estimates can understate tax.
- CA tax-table rounding rules for lower-income table lookups are not modeled; this uses the official rate schedules.
- Other states with pending or missing official data remain blocked.
