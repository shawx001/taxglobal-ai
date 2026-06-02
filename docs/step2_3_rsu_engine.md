# Step 2.3 - RSU Tax Engine

## Purpose

Implement `rsu_tax_estimate` for the MVP RSU workflow: vesting ordinary income tax plus an optional sale scenario comparing short-term and long-term capital gains treatment.

## What Changed

- Added `rsu_tax_estimate` to the tax engine.
- Exported the function from `engine.__init__`.
- Reused existing Decimal, date parsing, ordinary bracket, LTCG stacking, and invalid input helpers.
- Added RSU golden fixtures for vest-only, long-term sale, short-term sale, and invalid input paths.
- Added boundary tests for exactly-one-year holding period and sale below FMV.
- Added the Step 2.3 design and delivery documents.
- Added `docs/feature_status.md` to version control as the live feature ledger.

## Acceptance Criteria

- Vest-only golden case returns ordinary income `$50,000.00` and vest income tax `$12,216.00`.
- Long-term sale scenario returns `$30,000.00` capital gain and `$4,500.00` capital gains tax.
- Short-term sale scenario returns `$30,000.00` capital gain and `$9,600.00` ordinary capital gains tax.
- Invalid shares and sale-before-vest scenarios return `invalid_input`.
- FICA scope is disclosed in assumptions and delegated to `fica_tax`.
- Unit tests, golden tests, ruff, data validation, diff check, and prototype hash check pass.

## Files Changed

- `engine/__init__.py`
- `engine/tax_engine.py`
- `tests/test_engine.py`
- `tests/golden/rsu_tax_estimate.json`
- `docs/feature_status.md`
- `docs/step2_3_design_rsu.md`
- `docs/step2_3_rsu_engine.md`

## Known Limits

- FICA is not calculated here; callers should use `fica_tax` for wages.
- ISO, ESPP, NQSO, 83(b), AMT, withholding shortfalls, and multi-vest aggregation are out of scope.
- The sale scenario is caller-provided and is not a stock price forecast.
