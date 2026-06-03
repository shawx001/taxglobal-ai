# Step 5.3 - FEIE Frontend API Integration

## Purpose

Move the FEIE panel from frontend prototype calculations to the backend `/calc/feie` rule engine result.

## What Changed

- Added `TaxGlobalApi.feie(...)` in `frontend/api.js`.
- Rebuilt `calcFEIE()` in `frontend/index.html` to call `/calc/feie` with:
  - `foreign_earned_income`
  - `days_abroad`
- Displayed backend FEIE results:
  - 330-day physical presence test result
  - excluded income
  - remaining U.S. taxable income
  - citations
  - assumptions
- Removed frontend FEIE fake calculations:
  - hardcoded `limit=130000`
  - local `excluded=min(...)`
  - isolated `usTaxOnRemaining=bracketTax(...)`
- Removed the misleading "U.S. remaining tax" row.
- Replaced it with a plain explanation that remaining income must be combined with other income in the ordinary-income module for accurate stacked-rate calculation.
- Removed the FEIE country selector and hardcoded local-tax note.
- Kept the existing notice that FEIE only applies to foreign earned income, not passive foreign income.

## Acceptance Criteria

- FEIE exclusion logic comes from `/calc/feie`, not frontend constants.
- The FEIE panel no longer presents standalone U.S. tax on remaining income.
- The FEIE panel no longer shows hardcoded foreign local-tax assumptions.
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
- FEIE panel smoke:
  - `$140,000` foreign earned income and `340` days abroad returns a passed 330-day test, `$130,000` excluded, and `$10,000` remaining income.
  - `$140,000` foreign earned income and `329` days abroad returns a failed 330-day test, `$0` excluded, and `$140,000` remaining income.

## Files Changed

- `frontend/api.js`
- `frontend/index.html`
- `docs/step5_3_design_feie_frontend.md`
- `docs/step5_3_feie_frontend.md`

## Known Limits

- Foreign local tax, treaty analysis, FTC, and passive foreign income remain out of scope for this panel.
- Remaining foreign earned income is not automatically merged into the ordinary-income module yet; that is pending profile income buckets in `REQ-001`.
- Self-employment, crypto, and Nexus frontend panels still await backend API migration.
