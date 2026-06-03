# Step 2.6 Delivery - Crypto State Tax (REQ-012)

Goal: extend `crypto_gain_estimate` so crypto net capital gains can optionally include state tax for the five supported income-tax states and Washington capital gains excise.

## What Changed

- Archived Washington DOR capital gains tax guidance and tiered-rate special notice.
- Added `capital_gains_treatment: ordinary_income` to CA/NY/GA/IL/CO `tax_base` data.
- Added WA `capital_gains_excise` data for tax year 2025:
  - standard deduction: `$278,000`
  - base rate: `7%`
  - additional rate: `2.9%`
  - tier threshold: `$1,000,000` taxable Washington capital gains
  - long-term only
- Added `_crypto_state_tax` in `engine/tax_engine.py`.
- Added optional `state_code` to `crypto_gain_estimate` and `/calc/crypto`.
- Kept `tax_estimate.total` as federal + NIIT only; added `total_tax_including_state` when `state_code` is provided.
- Added golden and engine tests for CA/NY/GA/IL/CO/FL/MA/WA.
- Extended Step 1 data validation for state crypto capital gains data.

## Golden Values

Dataset: FIFO BTC example with net short-term gain `$5,000`, net long-term gain `$30,000`, `other_taxable_income=100000`, single.

- CA: `$3,255.00`
- NY: `$2,100.00`
- GA: `$1,816.50`
- IL: `$1,732.50`
- CO: `$1,540.00`
- FL: `$0.00`
- MA: nested `state.status=not_covered`
- WA: `$0.00` because long-term gain is below the `$278,000` standard deduction

WA large long-term cases:

- LT gain `$500,000`: WA tax `$15,540.00`
- LT gain `$1,500,000`: WA tax `$91,978.00`
- ST gain `$500,000`, LT gain `$0`: WA tax `$0.00`

## Validation

- Existing federal crypto behavior is preserved when `state_code` is omitted.
- State income-tax states use incremental state tax: tax on other income plus crypto gain minus tax on other income.
- WA uses taxable Washington capital gains after the standard deduction for the `$1,000,000` tier, matching the archived DOR special notice wording.

## Known Limits

- Frontend state selection/display is not part of this step.
- `other_taxable_income` is reused as the state stacking base; this matches the MVP `income_tax_summary` approximation.
- WA residency/allocation is assumed in-state.
- WA exempt asset categories are not modeled, but crypto is treated as a non-exempt capital asset.
- State-specific credits and residual adjustments remain outside this step.
