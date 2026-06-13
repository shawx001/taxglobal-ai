# Codex Prompt: Engine Audit PR 1 — Data Accuracy Fixes

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `docs/engine_audit_report.md` (Part 6: Shaw Decision)

## Task

Fix 31 data accuracy issues found by the engine audit (comparing our `data/tax_years/2025/*.json` against OpenAccountants research-verified tax skills). Shaw approved all fixes with the rule "以 OpenAccountants 为主" (adopt OA values for all discrepancies). These are pure data-file edits — no engine code changes.

## Core Constraints

1. **Only modify data files** — do NOT touch any `.py` files
2. **Preserve JSON schema** — same key names, same nesting structure, same types
3. **Preserve all existing keys** that are NOT being fixed — do not add or remove fields unless explicitly specified
4. **Run existing tests after changes** — `python -m unittest discover -s tests` must still pass
5. **Run lint** — `python -m ruff check engine backend tests` must still pass
6. **One commit per logical group** (federal fix + state fixes can be one commit)

## File 1: `data/tax_years/2025/us_qbi.json`

### Fix Q1-Q2: QBI MFS Phase-in Window and Upper Limit

Change `phase_in_window.married_filing_separately` from `50000` to `25000`.
Change `upper_limit.married_filing_separately` from `247300` to `222300`.

The `taxable_income_threshold.married_filing_separately` stays at `197300` (confirmed match).

**Before:**
```json
"phase_in_window": {
  "single": 50000,
  "head_of_household": 50000,
  "married_filing_separately": 50000,
  "qualifying_surviving_spouse": 50000,
  "married_filing_jointly": 100000
},
"upper_limit": {
  "single": 247300,
  "head_of_household": 247300,
  "married_filing_separately": 247300,
  "qualifying_surviving_spouse": 247300,
  "married_filing_jointly": 494600
}
```

**After:**
```json
"phase_in_window": {
  "single": 50000,
  "head_of_household": 50000,
  "married_filing_separately": 25000,
  "qualifying_surviving_spouse": 50000,
  "married_filing_jointly": 100000
},
"upper_limit": {
  "single": 247300,
  "head_of_household": 247300,
  "married_filing_separately": 222300,
  "qualifying_surviving_spouse": 247300,
  "married_filing_jointly": 494600
}
```

---

## File 2: `data/tax_years/2025/us_states.json`

All fixes are inside the top-level `"states"` object. Each state is keyed by uppercase abbreviation (e.g., `"VT"`, `"ND"`).

### Bracket format reference
Each bracket tier is `{"up_to": <int|null>, "rate": <float>}`. `null` means unlimited (top bracket).

---

### Fix S1: VT — tax_base start_from + remove standard_deduction

VT starts from federal taxable income, not federal AGI. It has no separate state standard deduction.

1. Change `states.VT.tax_base.start_from` from `"federal_agi"` to `"federal_taxable_income"`
2. Remove the `states.VT.tax_base.standard_deduction` object entirely (VT piggybacks on federal)
3. Update `states.VT.notes` to reflect this change

### Fix S6: VT MFS brackets

Replace `states.VT.brackets.married_filing_separately` with:
```json
[
  {"up_to": 39975, "rate": 0.0335},
  {"up_to": 96650, "rate": 0.066},
  {"up_to": 147300, "rate": 0.076},
  {"up_to": null, "rate": 0.0875}
]
```

### Fix S7: VT HoH brackets

Replace `states.VT.brackets.head_of_household` with:
```json
[
  {"up_to": 64200, "rate": 0.0335},
  {"up_to": 165700, "rate": 0.066},
  {"up_to": 268300, "rate": 0.076},
  {"up_to": null, "rate": 0.0875}
]
```

### Fix S8: VT Single bracket 2 threshold

In `states.VT.brackets.single`, change tier 2 `up_to` from `116350` to `116000`.

Also in `states.VT.brackets.married_filing_jointly`:
- Change tier 2 `up_to` from `193350` to `193300`
- Change tier 3 `up_to` from `294650` to `294600`

---

### Fix S2: MN — tax_base start_from

Change `states.MN.tax_base.start_from` from `"federal_agi"` to `"federal_taxable_income"`.

Note: Keep the `standard_deduction` field for now — MN may use it for state-specific adjustments. Add a note that MN starts from federal taxable income per MN DOR.

---

### Fix S3: MS — tax_base start_from

Change `states.MS.tax_base.start_from` from `"federal_agi"` to `"state_specific"`.

Update `states.MS.notes` or `states.MS.tax_base.notes` to include: "Mississippi uses its own independent income computation, not starting from federal AGI or federal taxable income."

### Fix S25: MS HOH combined standard_deduction

Change `states.MS.tax_base.standard_deduction.head_of_household` from `9400` to `11400`.

(This is $3,400 standard deduction + $8,000 personal exemption for HOH per OA.)

---

### Fix S4: OR — tax_base start_from

Change `states.OR.tax_base.start_from` from `"federal_agi"` to `"federal_taxable_income"`.

---

### Fix S5: CO — qbi_addback

Change `states.CO.tax_base.qbi_addback` from `true` to `false`.

Update the notes to clarify: "Colorado starts from federal taxable income which is post-QBI deduction. No separate QBI addback needed for the base computation."

---

### Fix S10-S12: ND — MFJ, MFS, HoH brackets

Replace `states.ND.brackets.married_filing_jointly` with:
```json
[
  {"up_to": 80975, "rate": 0},
  {"up_to": 298075, "rate": 0.0195},
  {"up_to": null, "rate": 0.025}
]
```

Replace `states.ND.brackets.married_filing_separately` with:
```json
[
  {"up_to": 40475, "rate": 0},
  {"up_to": 149025, "rate": 0.0195},
  {"up_to": null, "rate": 0.025}
]
```

Replace `states.ND.brackets.head_of_household` with:
```json
[
  {"up_to": 64950, "rate": 0},
  {"up_to": 271450, "rate": 0.0195},
  {"up_to": null, "rate": 0.025}
]
```

Keep `single` and `qualifying_surviving_spouse` as-is (they match OA).

---

### Fix S13-S15: NM — Single, MFJ, MFS brackets

Replace `states.NM.brackets.single` with:
```json
[
  {"up_to": 5500, "rate": 0.015},
  {"up_to": 16500, "rate": 0.032},
  {"up_to": 33500, "rate": 0.043},
  {"up_to": 66500, "rate": 0.047},
  {"up_to": 210000, "rate": 0.049},
  {"up_to": null, "rate": 0.059}
]
```

Replace `states.NM.brackets.married_filing_jointly` with:
```json
[
  {"up_to": 8000, "rate": 0.015},
  {"up_to": 25000, "rate": 0.032},
  {"up_to": 50000, "rate": 0.043},
  {"up_to": 100000, "rate": 0.047},
  {"up_to": 315000, "rate": 0.049},
  {"up_to": null, "rate": 0.059}
]
```

Replace `states.NM.brackets.married_filing_separately` with:
```json
[
  {"up_to": 4000, "rate": 0.015},
  {"up_to": 12500, "rate": 0.032},
  {"up_to": 25000, "rate": 0.043},
  {"up_to": 50000, "rate": 0.047},
  {"up_to": 157500, "rate": 0.049},
  {"up_to": null, "rate": 0.059}
]
```

Also update `head_of_household` and `qualifying_surviving_spouse` to match the `married_filing_jointly` schedule (NM uses MFJ brackets for HOH/QSS per OA).

---

### Fix S16: WI — Bracket 2 upper thresholds

In `states.WI.brackets.single`, change tier 2 `up_to` from `29370` to `50480`.
In `states.WI.brackets.married_filing_jointly`, change tier 2 `up_to` from `39150` to `67300`.
In `states.WI.brackets.married_filing_separately`, change tier 2 `up_to` from `19580` to `33650`.
In `states.WI.brackets.head_of_household`, change tier 2 `up_to` to `50480` (same as single per OA).
In `states.WI.brackets.qualifying_surviving_spouse`, change tier 2 `up_to` to `67300` (same as MFJ per OA).

---

### Fix S17: AL — HOH brackets

Replace `states.AL.brackets.head_of_household` to use the **Single** bracket schedule (not MFJ):
```json
[
  {"up_to": 500, "rate": 0.02},
  {"up_to": 3000, "rate": 0.04},
  {"up_to": null, "rate": 0.05}
]
```

(This should match the `single` brackets exactly.)

---

### Fix S18: AR — All bracket thresholds

Replace `states.AR.brackets.single` (and all other filing statuses that share this schedule) with:
```json
[
  {"up_to": 5499, "rate": 0},
  {"up_to": 10899, "rate": 0.02},
  {"up_to": 15599, "rate": 0.03},
  {"up_to": 25699, "rate": 0.034},
  {"up_to": null, "rate": 0.039}
]
```

Apply the same values to ALL filing statuses in AR (AR uses uniform brackets).

---

### Fix S19: OK — MFJ top bracket

In `states.OK.brackets.married_filing_jointly`, change the last tier's threshold:
The tier before the top bracket should have `up_to` changed from `12200` to `14400`.

Full MFJ brackets should be:
```json
[
  {"up_to": 2000, "rate": 0.0025},
  {"up_to": 5000, "rate": 0.0075},
  {"up_to": 7500, "rate": 0.0175},
  {"up_to": 9800, "rate": 0.0275},
  {"up_to": 14400, "rate": 0.0375},
  {"up_to": null, "rate": 0.0475}
]
```

---

### Fix S20: MT — HoH bracket threshold

In `states.MT.brackets.head_of_household`, change tier 1 `up_to` from `30750` to `31700`.

---

### Fix S21: IN — Flat rate

Change `states.IN.flat_rate` from `0.03` to `0.0305`.

---

### Fix S22: IL — Personal exemption

Change `states.IL.tax_base.exemption_allowance_per_person` from `2850` to `2625`.

---

### Fix S23: IN — Dependent exemption note

In `states.IN.tax_base.notes`, change `$3,000 per dependent` to `$1,500 per dependent`.

---

### Fix S24: VA — Standard deduction (2025 values)

Replace `states.VA.tax_base.standard_deduction` with:
```json
{
  "single": 9430,
  "married_filing_jointly": 18860,
  "married_filing_separately": 9430,
  "head_of_household": 9430,
  "qualifying_surviving_spouse": 18430
}
```

(These are 2025 combined values: $8,500 std ded + $930 personal exemption = $9,430 single.)

---

### Fix S26: OH — Personal exemption (modeled as std deduction)

Change `states.OH.tax_base.standard_deduction.single` from `1850` to `1900`.
Change `states.OH.tax_base.standard_deduction.married_filing_jointly` from `3700` to `3800`.
Change `states.OH.tax_base.standard_deduction.married_filing_separately` from `1850` to `1900`.
Change `states.OH.tax_base.standard_deduction.head_of_household` from `1850` to `1900`.
Change `states.OH.tax_base.standard_deduction.qualifying_surviving_spouse` from `1850` to `1900`.

(These are the >$80K MAGI tier personal exemption per OA.)

---

### Fix S27: NE — Personal exemption credit note

If `states.NE` has a personal exemption credit value in notes or tax_base, change `$171` to `$157`. If it's only in notes text, update that string.

---

### Fix S28: WV — MFS brackets (halved)

Replace `states.WV.brackets.married_filing_separately` with:
```json
[
  {"up_to": 5000, "rate": 0.0222},
  {"up_to": 12500, "rate": 0.0296},
  {"up_to": 20000, "rate": 0.0333},
  {"up_to": 30000, "rate": 0.0444},
  {"up_to": null, "rate": 0.0482}
]
```

---

### Fix S29: ME — Add 4th bracket (surcharge)

Add a 4th tier to `states.ME.brackets.single` and `states.ME.brackets.married_filing_separately`:
```json
{"up_to": null, "rate": 0.0915}
```

Change the current top bracket (rate 0.0715) from `"up_to": null` to `"up_to": 1000000`.

For `states.ME.brackets.married_filing_jointly` (and `qualifying_surviving_spouse` / `head_of_household` if they exist):
Change current top bracket from `"up_to": null` to `"up_to": 1500000` (MFJ threshold per OA).
Add: `{"up_to": null, "rate": 0.0915}`.

---

### Fix CA1: CA — All bracket thresholds (adopt OA projected values)

Replace ALL CA bracket thresholds with OA values. Rates stay the same.

**Single/MFS brackets:**
```json
[
  {"up_to": 10756, "rate": 0.01},
  {"up_to": 25499, "rate": 0.02},
  {"up_to": 40245, "rate": 0.04},
  {"up_to": 55866, "rate": 0.06},
  {"up_to": 70612, "rate": 0.08},
  {"up_to": 360659, "rate": 0.093},
  {"up_to": 432791, "rate": 0.103},
  {"up_to": 721314, "rate": 0.113},
  {"up_to": null, "rate": 0.123}
]
```

**MFJ/QSS brackets** (double Single):
```json
[
  {"up_to": 21512, "rate": 0.01},
  {"up_to": 50998, "rate": 0.02},
  {"up_to": 80490, "rate": 0.04},
  {"up_to": 111732, "rate": 0.06},
  {"up_to": 141224, "rate": 0.08},
  {"up_to": 721318, "rate": 0.093},
  {"up_to": 865582, "rate": 0.103},
  {"up_to": 1442628, "rate": 0.113},
  {"up_to": null, "rate": 0.123}
]
```

**HoH brackets** — keep our existing HOH schedule structure (OA incorrectly merges HOH with Single, but CA has distinct HOH brackets). Scale our HOH thresholds down by the same ~3% ratio as Single.

To calculate HOH: multiply each of our current HOH thresholds by (OA_single / our_single) for each tier.

| Tier | Our Single | OA Single | Ratio | Our HoH | New HoH (rounded to integer) |
|---|---|---|---|---|---|
| 1 | 11079 | 10756 | 0.97085 | 22173 | 21527 |
| 2 | 26264 | 25499 | 0.97087 | 52530 | 51000 |
| 3 | 41452 | 40245 | 0.97088 | 67716 | 65745 |
| 4 | 57542 | 55866 | 0.97087 | 83805 | 81365 |
| 5 | 72724 | 70612 | 0.97096 | 98990 | 96119 |
| 6 | 371479 | 360659 | 0.97088 | 505208 | 490500 |
| 7 | 445771 | 432791 | 0.97088 | 606251 | 588609 |
| 8 | 742953 | 721314 | 0.97088 | 1010417 | 980992 |

Use these scaled HoH values. Add a note in the CA section: "HOH brackets are CA-specific (not same as Single); thresholds scaled to match OA 2025 projected indexing. OA does not provide separate HOH thresholds. Verify against FTB 2025 Form 540."

**CA Standard deduction:**
```json
{
  "single": 5540,
  "married_filing_separately": 5540,
  "married_filing_jointly": 11080,
  "head_of_household": 11080,
  "qualifying_surviving_spouse": 11080
}
```

Add note: "Standard deduction values are OA 2025 projected. Verify against FTB 2025 Form 540. Source_id ca_2025_540_tax_rate_schedules may have more current values."

---

## New Tests

No new test files needed — this is data-only. But existing tests must still pass:

```powershell
python -m unittest discover -s tests
```

If any existing test hardcodes expected values from the changed data (e.g., tax amount for a specific income), those test expected values must be updated to match the new data. Look for tests that import or reference the specific JSON files being changed.

## Acceptance Gates

```powershell
python -m unittest discover -s tests
python -m ruff check engine backend tests
git diff --check
```

Verify the changes by spot-checking a few values:
```python
import json
d = json.load(open("data/tax_years/2025/us_states.json"))

# VT should start from federal_taxable_income
assert d["states"]["VT"]["tax_base"]["start_from"] == "federal_taxable_income"
assert "standard_deduction" not in d["states"]["VT"]["tax_base"]

# ND MFJ bracket 1
assert d["states"]["ND"]["brackets"]["married_filing_jointly"][0]["up_to"] == 80975

# WI single bracket 2
assert d["states"]["WI"]["brackets"]["single"][1]["up_to"] == 50480

# IN rate
assert d["states"]["IN"]["flat_rate"] == 0.0305

# QBI MFS phase-in
q = json.load(open("data/tax_years/2025/us_qbi.json"))
assert q["qbi_deduction"]["phase_in_window"]["married_filing_separately"] == 25000
assert q["qbi_deduction"]["upper_limit"]["married_filing_separately"] == 222300
```

## Commit Format

```
fix(data): correct 31 tax data accuracy issues from engine audit

Fixes bracket thresholds for VT, ND, NM, WI, AL, AR, OK, MT, WV, ME, CA.
Fixes tax_base start_from for VT, MN, MS, OR. Removes CO qbi_addback.
Fixes flat rates (IN), exemptions (IL, OH, NE), deductions (VA, MS).
Fixes QBI MFS phase-in window ($50K→$25K) and upper limit ($247.3K→$222.3K).
All changes per engine audit report: docs/engine_audit_report.md
Decision rule: adopt OpenAccountants values (Shaw approved 2026-06-09).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
