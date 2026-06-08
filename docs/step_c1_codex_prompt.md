# Step C1 Codex Prompt — No-Tax States (AK, NH, SD, TN, WY) + Activate TX

## Context
You are working on TaxGlobal AI, a US tax calculation engine. Read `/AGENTS.md` first (project-wide rules).

**Goal:** Add 5 new no-income-tax states and activate Texas. This is batch C1 of the 50-state coverage plan. **Zero engine code changes** — data + tests only.

**Branch:** `feature/step-c1-no-tax`
**Base:** `main`

## Step 0 — Preserve & commit untracked docs

```bash
git checkout -b feature/step-c1-no-tax
git add docs/step_c1_design_no_tax_states.md docs/step_c1_codex_prompt.md docs/step_c_all_states_plan.md
git commit -m "docs: add Step C1 design doc, Codex prompt, and 50-state plan

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

## Step 1 — Add source manifest entries

In `data/sources/us/2025/source_manifest.json`, add 6 entries to the `sources` array (before the `failed_sources` section). Use `status: "not_archived"` since these are general reference pages, not specific PDFs.

```json
{
  "source_id": "ak_dor_no_income_tax",
  "source_url": "https://tax.alaska.gov/programs/programs/index.aspx?10001",
  "publisher": "Alaska Department of Revenue",
  "description": "Alaska Department of Revenue states Alaska has no personal income tax.",
  "status": "not_archived",
  "notes": "Alaska DOR general tax page confirming no personal income tax. Alaska has never imposed a state personal income tax."
},
{
  "source_id": "nh_dra_interest_dividends_repeal",
  "source_url": "https://www.revenue.nh.gov/faq/interest-dividend-tax.htm",
  "publisher": "New Hampshire Department of Revenue Administration",
  "description": "NH DRA confirms the Interest and Dividends Tax was repealed effective January 1, 2025.",
  "status": "not_archived",
  "notes": "NH DRA FAQ page on Interest and Dividends Tax repeal. Per HB 2 (2023 session), the I&D tax (RSA 77) phased down from 5% to 3% (2023), 2% (2024), and was fully repealed effective 2025-01-01. For tax year 2025+, NH has no personal income tax."
},
{
  "source_id": "sd_dor_no_income_tax",
  "source_url": "https://dor.sd.gov/individuals/taxes/",
  "publisher": "South Dakota Department of Revenue",
  "description": "South Dakota DOR states South Dakota does not have a personal income tax.",
  "status": "not_archived",
  "notes": "SD DOR individuals tax page confirming no individual income tax. South Dakota has never imposed a state personal income tax."
},
{
  "source_id": "tn_dor_hall_tax_repeal",
  "source_url": "https://www.tn.gov/revenue/taxes/hall-income-tax.html",
  "publisher": "Tennessee Department of Revenue",
  "description": "Tennessee DOR confirms the Hall Income Tax was fully repealed effective January 1, 2021.",
  "status": "not_archived",
  "notes": "TN DOR Hall Income Tax page. The Hall Tax (on interest and dividend income) was phased out per Public Chapter 3 (2016) and fully repealed effective 2021-01-01. For tax year 2021+, Tennessee has no state income tax."
},
{
  "source_id": "wy_dor_no_income_tax",
  "source_url": "https://revenue.wyo.gov/tax-types",
  "publisher": "Wyoming Department of Revenue",
  "description": "Wyoming DOR states Wyoming does not have an individual income tax.",
  "status": "not_archived",
  "notes": "WY DOR tax types page confirming no individual income tax. Wyoming has never imposed a state personal income tax."
},
{
  "source_id": "tx_comptroller_no_income_tax",
  "source_url": "https://comptroller.texas.gov/taxes/",
  "publisher": "Texas Comptroller of Public Accounts",
  "description": "Texas Comptroller states Texas has no state income tax, prohibited by Article VIII Section 24-a of the Texas Constitution.",
  "status": "not_archived",
  "notes": "TX Comptroller taxes overview page confirming no personal income tax. Article VIII Section 24-a of the Texas Constitution prohibits an individual income tax unless approved by voters in a constitutional amendment election."
}
```

## Step 2 — Add states to `data/tax_years/2025/us_states.json`

Add 5 new state entries in the `states` object. Insert them in alphabetical order among existing entries. Each follows the FL/NV pattern exactly:

```json
"AK": {
  "name": "Alaska",
  "income_tax_type": "none",
  "status": "effective",
  "effective_date": "2025-01-01",
  "flat_rate": 0,
  "source_ids": ["ak_dor_no_income_tax"],
  "citation": "Alaska Department of Revenue states Alaska does not impose a personal income tax.",
  "state_parameter_year": 2025
},
"NH": {
  "name": "New Hampshire",
  "income_tax_type": "none",
  "status": "effective",
  "effective_date": "2025-01-01",
  "flat_rate": 0,
  "source_ids": ["nh_dra_interest_dividends_repeal"],
  "citation": "New Hampshire Department of Revenue Administration confirms the Interest and Dividends Tax was fully repealed effective January 1, 2025, per HB 2 (2023 session).",
  "notes": "New Hampshire historically taxed interest and dividend income (Hall-type tax under RSA 77). The tax rate was phased down from 5% to 3% (2023), 2% (2024), and fully repealed effective 2025-01-01. For tax year 2025+, NH imposes no personal income tax.",
  "state_parameter_year": 2025
},
"SD": {
  "name": "South Dakota",
  "income_tax_type": "none",
  "status": "effective",
  "effective_date": "2025-01-01",
  "flat_rate": 0,
  "source_ids": ["sd_dor_no_income_tax"],
  "citation": "South Dakota Department of Revenue states South Dakota does not have an individual income tax.",
  "state_parameter_year": 2025
},
"TN": {
  "name": "Tennessee",
  "income_tax_type": "none",
  "status": "effective",
  "effective_date": "2025-01-01",
  "flat_rate": 0,
  "source_ids": ["tn_dor_hall_tax_repeal"],
  "citation": "Tennessee Department of Revenue confirms the Hall Income Tax on interest and dividends was fully repealed effective January 1, 2021.",
  "notes": "Tennessee's Hall Income Tax (on interest and dividend income) was phased out per Public Chapter 3 (2016) and fully repealed effective 2021-01-01. For tax year 2021+, Tennessee imposes no state income tax.",
  "state_parameter_year": 2025
},
"WY": {
  "name": "Wyoming",
  "income_tax_type": "none",
  "status": "effective",
  "effective_date": "2025-01-01",
  "flat_rate": 0,
  "source_ids": ["wy_dor_no_income_tax"],
  "citation": "Wyoming Department of Revenue states Wyoming does not have an individual income tax.",
  "state_parameter_year": 2025
}
```

**Activate TX** — replace the existing TX entry entirely:

```json
"TX": {
  "name": "Texas",
  "income_tax_type": "none",
  "status": "effective",
  "effective_date": "2025-01-01",
  "flat_rate": 0,
  "source_ids": ["tx_comptroller_no_income_tax"],
  "citation": "Texas Comptroller of Public Accounts states Texas has no state income tax, constitutionally prohibited by Article VIII Section 24-a.",
  "state_parameter_year": 2025
}
```

## Step 3 — Add states to `data/tax_years/2026/us_states.json`

Apply the **identical** entries from Step 2 to the 2026 file. Same data, same `state_parameter_year: 2025` (parameters confirmed for 2025, still valid for 2026 since zero-tax doesn't change).

For TX in 2026: replace the existing `source_pending` entry with the same `effective` entry as 2025.

## Step 4 — Update golden tests

### 4a. `tests/golden/state_income_tax.json`

Add 5 new test cases (after existing `wa_zero` case, before `il_flat`). Replace the `tx_blocked` case with `tx_zero`.

New cases to add:
```json
{
  "name": "ak_zero",
  "input": {"state_code": "AK", "taxable_income": 100000},
  "expected": {"status": "ok", "rate": 0, "tax": 0.00}
},
{
  "name": "nh_zero",
  "input": {"state_code": "NH", "taxable_income": 100000},
  "expected": {"status": "ok", "rate": 0, "tax": 0.00}
},
{
  "name": "sd_zero",
  "input": {"state_code": "SD", "taxable_income": 100000},
  "expected": {"status": "ok", "rate": 0, "tax": 0.00}
},
{
  "name": "tn_zero",
  "input": {"state_code": "TN", "taxable_income": 100000},
  "expected": {"status": "ok", "rate": 0, "tax": 0.00}
},
{
  "name": "wy_zero",
  "input": {"state_code": "WY", "taxable_income": 100000},
  "expected": {"status": "ok", "rate": 0, "tax": 0.00}
}
```

Replace `tx_blocked` with:
```json
{
  "name": "tx_zero",
  "input": {"state_code": "TX", "taxable_income": 100000},
  "expected": {"status": "ok", "rate": 0, "tax": 0.00}
}
```

### 4b. `tests/golden/income_tax_summary_2026.json`

No changes needed — existing golden summary cases don't use any of these 6 states.

## Step 5 — Update test_engine.py

Search for any test that references TX as `not_covered` or `source_pending` and update it to expect `status: "ok"`. Specifically look for:
- Any assertion like `"TX"` + `"not_covered"` → change to expect `"ok"` with `tax == 0`
- The golden test runner `test_state_income_tax_golden` will automatically pick up the new cases

If there's a test like `test_state_income_tax_source_pending_returns_not_covered` that uses TX as the example, switch it to use MA (which is still source_pending).

## Step 6 — Update validate_step1_data.ps1

Add spot-check assertions after the existing TX/PA/OR checks. For 2025 section:
```powershell
# C1: No-tax states
if ($states.states.AK.income_tax_type -ne "none") {
  throw "Alaska must be income_tax_type none"
}
if ($states.states.AK.status -ne "effective") {
  throw "Alaska must be effective"
}
if ($states.states.TX.status -ne "effective") {
  throw "Texas must be effective (no longer source_pending)"
}
if ($states.states.NH.income_tax_type -ne "none") {
  throw "New Hampshire must be income_tax_type none"
}
```

For 2026 section, add matching assertions:
```powershell
if ($states2026.states.AK.income_tax_type -ne "none") {
  throw "2026 Alaska must be income_tax_type none"
}
if ($states2026.states.TX.status -ne "effective") {
  throw "2026 Texas must be effective"
}
if ($states2026.states.NH.income_tax_type -ne "none") {
  throw "2026 New Hampshire must be income_tax_type none"
}
```

## Step 7 — Verify

Run all gates:
```bash
python -m unittest discover -s tests -v
python -m ruff check engine backend tests
powershell -ExecutionPolicy Bypass -File tests/validate_step1_data.ps1
git diff --check
```

All must pass. Expected: no engine code changes, ~6 new golden cases, all existing tests unchanged.

## Step 8 — Commit & PR

```bash
git add -A
git commit -m "feat(states): add no-tax states AK NH SD TN WY and activate TX (Step C1)

Add 5 new zero-income-tax states and activate Texas from source_pending.
All 6 states use income_tax_type: none with flat_rate: 0.
Brings state coverage from 11 effective to 17 effective.

- AK: Alaska (never had income tax)
- NH: New Hampshire (I&D tax repealed 2025-01-01)
- SD: South Dakota (never had income tax)
- TN: Tennessee (Hall Tax repealed 2021-01-01)
- WY: Wyoming (never had income tax)
- TX: Texas (constitutionally prohibited)

Each state has source_ids in source_manifest.json.
Golden tests added for all 6 states; TX test updated from
not_covered to ok.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

Then open PR:
```bash
gh pr create --title "Step C1: add no-tax states AK NH SD TN WY + activate TX" \
  --body "## Summary
- Add 5 new zero-income-tax states: AK, NH, SD, TN, WY
- Activate TX from source_pending to effective
- Zero engine code changes — data + tests only
- State coverage: 11 → 17 effective states

## Changes
- \`data/tax_years/2025/us_states.json\` — add AK/NH/SD/TN/WY, activate TX
- \`data/tax_years/2026/us_states.json\` — same
- \`data/sources/us/2025/source_manifest.json\` — 6 new source entries
- \`tests/golden/state_income_tax.json\` — 5 new zero cases, TX blocked→ok
- \`tests/test_engine.py\` — update TX assertion if needed
- \`tests/validate_step1_data.ps1\` — spot-check assertions

## Test plan
- [ ] All 6 states return {status: ok, rate: 0, tax: 0}
- [ ] TX no longer returns not_covered
- [ ] MA still returns not_covered (unchanged)
- [ ] All existing state tests unchanged
- [ ] validate_step1_data.ps1 passes
- [ ] ruff clean"
```

## Constraints (from /AGENTS.md)
- Decimal precision: not applicable (all values are 0)
- Rules = data, never hardcoded: ✅ all from us_states.json
- No monolith: ✅ no engine changes
- One step per PR: ✅ C1 only
- source_ids must exist in manifest: ✅ added in Step 1
