# Step B2 NJ + PA gross-income states

Date: 2026-06-03
Branch: `feature/step-b2-nj-pa`

## Summary

Step B2 adds New Jersey and Pennsylvania individual income tax support to the combined
`income_tax_summary` path.

Both states use a gross-income-style state tax base for this MVP rather than federal AGI or
federal taxable income. The implementation adds one data-driven `gross_income` tax-base start
point and keeps NJ/PA behavior in state rule data instead of state-name branches.

## Changes

- Added archived official sources for:
  - New Jersey tax rate schedules.
  - New Jersey gross income tax overview and regular exemption.
  - Pennsylvania PIT rate.
  - Pennsylvania PIT overview.
- Added NJ and PA rules to both `data/tax_years/2025/us_states.json` and
  `data/tax_years/2026/us_states.json`.
- Added `_state_taxable_base(..., gross_income=...)` support for `start_from: "gross_income"`.
- Updated `income_tax_summary` to calculate `gross_income` as FEIE-before, federal above-line-deduction-before
  income buckets and pass it to the state tax-base helper.
- Added data-driven NJ no-tax gross-income thresholds so low-income NJ filers return zero state tax.
- Added a gross-income assumption for state-specific items not modeled.
- Added 2026 golden cases for NJ, PA, and NJ mixed W-2 plus long-term capital gains.

## Numeric Anchors

- NJ W-2 150,000 single: federal `24734.00`, payroll `11475.00`, NJ `7365.05`, total `43574.05`.
- PA W-2 150,000 single: federal `24734.00`, payroll `11475.00`, PA `4605.00`, total `40814.00`.
- NJ W-2 100,000 + long-term capital gain 50,000 single: NJ taxable base `149000.00`,
  NJ tax `7365.05`, total `35685.05`.

## Notes

- NJ Schedule I is used for single and married filing separately.
- NJ Schedule II is used for married filing jointly, head of household, and qualifying surviving spouse.
- PA is modeled as a flat 3.07% state income tax on the gross-income proxy.
- NJ pension exclusions and special deductions, PA class-of-income loss rules, local taxes, credits,
  and resident/source allocation are not modeled.
- OR is intentionally left for Step B2b.
