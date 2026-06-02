# Step 1.1 - Capital Gains and NIIT Data

## Purpose

Add the 2025 capital gains and Net Investment Income Tax data needed before implementing RSU and crypto tax estimates. This step only adds data, archived sources, and validation. It does not add engine functions.

## What Changed

- Archived IRS Topic 409 and IRS Topic 559 HTML pages under `data/sources/us/2025/raw/`.
- Added both archived sources to `data/sources/us/2025/source_manifest.json`.
- Reused the existing archived Rev. Proc. 2024-40 PDF for 2025 long-term capital gains thresholds.
- Added `data/tax_years/2025/us_capital_gains.json`.
- Extended `tests/validate_step1_data.ps1` to validate the capital gains data file.
- Added the Step 1.1 design document to version control.

## Acceptance Criteria

- Archived source hashes match `source_manifest.json`.
- `us_capital_gains.json` is valid JSON and has `tax_year: 2025`.
- Effective capital gains rules include `effective_date`.
- All `source_ids` resolve through `source_manifest.json`.
- Long-term capital gains brackets include all five filing statuses and each final bracket has `up_to: null`.
- NIIT thresholds include all five filing statuses and `rate` is `0.038`.
- Root `index.html` and `frontend/index.html` SHA-256 hashes remain identical.

## Files Changed

- `data/sources/us/2025/raw/irs_topic_409_capital_gains_and_losses.html`
- `data/sources/us/2025/raw/irs_topic_559_net_investment_income_tax.html`
- `data/sources/us/2025/source_manifest.json`
- `data/tax_years/2025/us_capital_gains.json`
- `tests/validate_step1_data.ps1`
- `docs/step1_1_design_capital_gains.md`
- `docs/step1_1_capital_gains_data.md`

## Source Checks

- IRS Topic 409 was archived for holding-period and short-term capital gains treatment.
- IRS Topic 559 was archived for NIIT rate and MAGI thresholds.
- Rev. Proc. 2024-40 was checked for the 2025 long-term capital gains thresholds, including married filing separately and qualifying surviving spouse.

## Known Limits

- This step does not implement `rsu_tax_estimate` or `crypto_gain_estimate`.
- Step 2.2 must handle capital gains stacking rules in engine code instead of treating LTCG brackets as ordinary marginal tax brackets.
