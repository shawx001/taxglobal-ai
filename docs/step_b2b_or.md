# Step B2b Delivery - Oregon state income tax

Date: 2026-06-07
Branch: `feature/step-b2b-or`

## Scope

Step B2b adds Oregon full-year resident income tax support to the combined
`income_tax_summary` state path. Oregon is modeled as a progressive income tax state
whose MVP taxable base starts from federal AGI, subtracts the Oregon standard
deduction, then subtracts a data-driven federal tax liability subtraction.

## Engine changes

- `engine/summary.py` now computes `federal_income_tax_liability` as federal ordinary
  income tax plus long-term capital gains tax. NIIT, W-2 FICA, additional Medicare,
  and self-employment tax are intentionally excluded from this value.
- `engine/summary.py` passes `federal_income_tax` explicitly into `_state_taxable_base`.
- `engine/state.py` keeps `_state_taxable_base` generic and supports
  `tax_base.federal_tax_subtraction.phaseout_table` for any `start_from:
  "federal_agi"` state.
- `engine/crypto.py` returns `not_covered` for standalone crypto state estimates
  when a state declares `federal_tax_subtraction`, because that path does not have
  full-return federal income tax liability context.
- No Oregon state-code branch was added.

## Data

Added Oregon to:

- `data/tax_years/2025/us_states.json`
- `data/tax_years/2026/us_states.json`

The 2026 Oregon block uses the 2025 Oregon parameters and declares
`state_parameter_year: 2025`.

Stored Oregon data includes:

- standard deduction by filing status,
- progressive rate brackets,
- federal tax liability subtraction phaseout tables for all filing statuses,
- source ids and assumptions.

## Sources

Archived official Oregon DOR files:

- `or_dor_or40_instructions_2025`
- `or_dor_pub_or17_2025`
- `or_dor_estimated_income_tax_2025`

The Form OR-40 instructions provide the federal tax liability subtraction worksheet
and AGI phaseout table. Publication OR-17 provides the standard deduction table.
The estimated income tax instructions provide the 2025 rate chart used for the
stored bracket thresholds.

## Golden values

- OR W-2 100,000 single:
  - federal income tax: 13,170.00
  - payroll tax: 7,650.00
  - federal tax liability subtraction: min(13,170, 8,500) = 8,500
  - Oregon taxable base: 100,000 - 2,835 - 8,500 = 88,665
  - Oregon tax: 7,449.19
  - total tax: 28,269.19
- OR W-2 129,000 single:
  - federal income tax liability: 19,694.00
  - phaseout table limit: 6,800
  - Oregon taxable base: 119,365.00
  - Oregon tax: 10,135.44
  - total tax: 39,697.94

## Assumptions and not modeled

- The MVP federal tax subtraction uses federal ordinary income tax plus long-term
  capital gains tax as the federal income tax liability proxy.
- Federal credits, Oregon-specific additions/subtractions, itemized deductions,
  exemption credits, kicker credit, other Oregon credits, local taxes, and
  resident/source allocation are not modeled.
- Married-filing-separately spouse itemization differences are approximated from
  the stored filing status because the MVP does not collect spouse itemization
  inputs.
- Standalone Oregon crypto state income tax is not covered until the crypto
  estimator has full-return federal income tax liability context.
- Official return instructions round return entries to whole dollars; this engine
  applies the phaseout table at cent precision.
- Oregon's 2025 published sources have a rate-chart threshold nuance: the user
  acceptance golden and archived OR estimated-tax instructions use the indexed
  single second bracket cap at 11,050, while the archived final OR-40 return chart
  presents tax constants that imply an 11,100 cap. This PR keeps the user-specified
  11,050 / 22,100 bracket caps and asks Claude to cross-check that source precedence.
