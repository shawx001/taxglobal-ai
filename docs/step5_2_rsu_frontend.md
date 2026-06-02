# Step 5.2 - RSU Frontend API Integration

## Purpose

Move the frontend RSU panel from prototype-only calculations to the backend `/calc/rsu` rule engine result.

## What Changed

- Added `TaxGlobalApi.rsu(...)` in `frontend/api.js`.
- Rebuilt the RSU panel inputs in `frontend/index.html`:
  - `other_taxable_income`
  - `shares_vested`
  - `fair_market_value_per_share`
  - `vest_date`
  - optional sale scenario: `sale_date` and `sale_price_per_share`
- Removed the prototype-only option value and future growth inputs.
- Replaced the old frontend RSU tax calculation with a `/calc/rsu` call.
- Displayed backend `vesting`, optional `hold_vs_sell`, citations, and assumptions.
- Added `REQ-006` in `docs/product_backlog.md` for a future standalone stock-options module.

## Acceptance Criteria

- RSU tax amounts are returned by `/calc/rsu`; the frontend only collects inputs and renders results.
- Old RSU growth and option-value prototype calculations are removed.
- Backend citations and assumptions remain visible.
- Error messages use the existing escaped API error rendering path.
- Root `index.html` remains frozen.

## Verification

- `python -m unittest discover -s tests -v`
- `ruff check engine backend tests`
- `pip-audit -r backend/requirements.txt`
- `powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1`
- `git diff --check`
- Root `index.html` SHA256 remains `833508998A7FF1C783646E5E8B35E8C66AB27AE5FF88193318C2A1F2007B4B69`.
- Browser smoke:
  - RSU panel calls `/calc/rsu`.
  - `1000` shares at `$50`, other taxable income `$150,000`, vest date `2024-03-01` returns ordinary income `$50,000` and vest income tax `$12,216`.
  - Sale scenario `2025-06-01` at `$80` returns long-term capital gains tax `$4,500`.

## Files Changed

- `frontend/api.js`
- `frontend/index.html`
- `docs/product_backlog.md`
- `docs/step5_2_design_rsu_frontend.md`
- `docs/step5_2_rsu_frontend.md`

## Known Limits

- Stock options (NQSO/ISO/ESPP) are explicitly out of scope and tracked as `REQ-006`.
- `other_taxable_income` is still manually entered; automatic profile income sync is pending `REQ-001`.
- RSU-related FICA is not included in this panel and remains handled by `fica_tax`.
- Other frontend modules still await backend API migration.
