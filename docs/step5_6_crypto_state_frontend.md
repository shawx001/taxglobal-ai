# Step 5.6 Delivery - Crypto State Tax Frontend

Goal: show the already-modeled crypto state tax from Step 2.6 in the crypto frontend, without changing tax calculation logic or the frozen root `index.html`.

## What Changed

- Added a crypto state selector in `frontend/index.html` with supported ordinary-income states (CA/NY/GA/IL/CO), WA capital gains excise, no-income-tax states (FL/NV), and not-covered examples (TX/MA).
- `calcCrypto()` now passes `state_code` to `/calc/crypto` only when a state is selected.
- FIFO/LIFO/HIFO method comparison now uses `result.total_tax_including_state` when present, so "cheapest" reflects the real total after state tax.
- The crypto result panel now renders state outcomes from engine fields only:
  - no selected state: keeps the federal + NIIT only warning
  - `not_covered`: gold honest warning and federal-only total
  - `no_state_income_tax`: state tax $0 and total including state
  - `excise`: WA long-term-only excise, long-term gain, deduction, taxable WA gain, rate, and total including state
  - `ordinary_income`: state income tax row and total including state
- Refactored crypto state not-covered responses in `engine/tax_engine.py` into `_crypto_state_not_covered()`.
- Renamed the WA state result field from `taxable_long_term_gain` to `long_term_gain`; the taxable post-deduction amount remains `taxable_washington_capital_gain`.

## Files Changed

- `engine/tax_engine.py`
- `frontend/index.html`
- `docs/product_backlog.md`
- `docs/feature_status.md`
- `docs/step5_6_design_crypto_state_frontend.md`
- `docs/step5_6_crypto_state_frontend.md`

## Validation

- Headless `/calc/crypto` checks cover CA, GA, WA below deduction, FL, MA, and WA large excise.
- Existing unittest golden coverage verifies that federal-only crypto behavior is unchanged when `state_code` is omitted.
- Full local gate for this PR:
  - `python -m unittest discover -s tests -v`
  - `ruff check engine backend tests`
  - `pip-audit -r backend/requirements.txt`
  - `powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1`
  - `git diff --check`
  - root `index.html` SHA256 remains `833508998A7FF1C783646E5E8B35E8C66AB27AE5FF88193318C2A1F2007B4B69`

## Known Limits

- Crypto state tax still depends on the states modeled in Step 2.6.
- WA modeling assumes in-state allocation and crypto assets; non-crypto exempt categories are not modeled here.
- Full multi-income total-tax merging remains a later REQ-009 step.
