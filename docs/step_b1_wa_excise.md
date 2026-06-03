# Step B1 WA capital gains excise

Date: 2026-06-03
Branch: `feature/step-b1-wa-excise`

## Summary

Step B1 connects modeled state capital gains excise rules into `income_tax_summary`.
The immediate gap was Washington: WA has no individual income tax, so summary previously showed
`state_income_tax = 0`, while large net long-term capital gains can owe the WA capital gains excise.

## Changes

- Added `state_capital_gains_excise` in `engine/state.py`.
- Updated `engine/crypto.py` so the existing WA crypto excise path calls the shared helper.
- Updated `engine/summary.py` so states with `capital_gains_excise` data add an excise amount outside the normal state income-tax line.
- Kept the summary path data-driven: it checks for `state_block["capital_gains_excise"]` and does not special-case WA by state code.
- Added 2026 income summary golden cases for WA long-term gains above and below the deduction, plus a short-term-only case.

## Numeric Anchors

- WA-1: `long_term_capital_gain=500000`, `state_code="WA"` -> WA excise `15540.00`, total tax `92107.50`.
- WA-2: `long_term_capital_gain=200000`, `state_code="WA"` -> WA excise `0.00`, total tax `20167.50`.
- WA-3: `short_term_capital_gain=300000`, `state_code="WA"` -> WA excise `0.00`.
- Crypto WA golden results remain unchanged after the helper extraction.

## Notes

- The normal state income-tax result is still shown separately. For WA it remains `0.00`.
- The excise assumes net long-term gains, non-exempt assets, state residency, and in-state allocation.
- No WA excise parameters or formulas were changed.
- Frontend files were not changed.
