# Engine Audit Report: TaxGlobal AI vs OpenAccountants

> **Date:** 2026-06-09
> **Auditor:** Claude (parallel subagent audit)
> **Scope:** Full — 5 federal modules + 51 states/territories
> **Sources:** `data/tax_years/2025/*.json` vs `.claude/skills/openaccountants/**/*.md`
> **Design Spec:** `docs/superpowers/specs/2026-06-09-skill-integration-design.md`

> **STATUS (2026-06-13)**: The PR-1 data fixes (`audit_pr1_data_fixes.md`)
> were applied to the **2025** data and are live. Two open items remain,
> tracked and fixed separately (NOT by blindly re-running the old prompt):
> 1. **2026 (default tax year) divergence** — the structural year-independent
>    fields (CO `qbi_addback`, MN/MS/VT `start_from`, VT std-ded) were never
>    propagated to `data/tax_years/2026/`, so the default path used stale
>    pre-fix values. Being corrected against official sources.
> 2. **Audit vs Step B2b conflict (OR) + year-dependent rate (IN)** — the
>    prompt's S4 (OR→federal_taxable_income) contradicts the later, officially
>    sourced Step B2b (OR = federal AGI − OR std ded − federal-tax subtraction);
>    and IN's flat rate is a scheduled annual cut (not a fixed value), so the
>    prompt's `0.0305` is suspect. **OpenAccountants is a third-party source,
>    not authoritative** — these are verified against state DOR before any edit.

---

## Executive Summary

| Category | Count | Meaning |
|---|---|---|
| ✅ Match | ~300+ | Both sources agree — no action needed |
| ⚠️ Discrepancy | **23** | Values differ — **Shaw决定：以OA为主全部采纳** |
| 🔴 Missing | **~110** | OA has it, we don't — auto-fix candidates |
| ℹ️ OA Lacks | ~50 | We have it, OA doesn't — keep ours |

**Zero federal value mismatches** where both sources have the same data point. All 53 overlapping federal values are exact matches. The 23 discrepancies are concentrated in state tax data — bracket thresholds, tax base starting points, and deduction values.

### Top Critical Findings

1. **5 states have wrong `tax_base` starting point** (VT, MN, MS, OR, CO) — structural computation errors
2. **4 states have systematically wrong bracket thresholds** (NM, ND, WI, VT) — not rounding errors, wrong data
3. **VA standard deduction uses 2026 values** in the 2025 data file
4. **CA bracket thresholds**: ~3% systematic difference — OA used projected estimates; ours likely correct (FTB source)
5. **ME/CA/NY missing high-earner surcharges** (ME 2% >$1M, CA MHST, NYC local tax)

---

## Part 1: Federal Modules

### 1.1 Federal Income Tax Brackets & Standard Deduction

**Result: 15 ✅ Match | 0 ⚠️ | 0 🔴 | 18 ℹ️ OA Lacks**

All 7 Single brackets and 7 MFJ brackets match exactly. Standard deduction (Single $15,000) confirmed. OA only provides Single/MFJ brackets (from crypto tax skill context), so HOH/MFS/QSS are "OA Lacks" — not gaps in our data.

### 1.2 FICA / Self-Employment Tax

**Result: 10 ✅ Match | 7 🔴 Missing | 0 ⚠️ | 3 ℹ️ OA Lacks**

All core values match (SS 6.2%/12.4%, wage base $176,100, Medicare 1.45%/2.9%, Additional Medicare 0.9%, thresholds $200K/$250K/$125K, net earnings 92.35%).

#### 🔴 Missing Items (auto-fix from OA):
| # | Item | OA Value | IRC Source | Status |
|---|---|---|---|---|
| F1 | Combined SE rate | 15.3% | IRC 1401(a)+(b)(1) | AUTO-FIX |
| F2 | Minimum SE earnings threshold | $400 | IRC 1402(b)(2), NOT indexed | AUTO-FIX |
| F3 | Deductible SE tax portion | 50% | IRC 164(f) | AUTO-FIX |
| F4 | Nonfarm optional method max | $7,320 | Schedule SE | AUTO-FIX |
| F5 | Nonfarm gross income threshold | $10,380 | Schedule SE | AUTO-FIX |
| F6 | Nonfarm profit threshold rule | <$7,320 net AND <72.189% gross | Schedule SE | AUTO-FIX |
| F7 | Optional method 5-year lifetime limit | 5 years | Schedule SE | AUTO-FIX |

### 1.3 QBI §199A Deduction

**Result: 13 ✅ Match | 14 🔴 Missing | 2 ⚠️ Disputed | 0 ℹ️ OA Lacks**

Core rate (20%), thresholds ($197,300/$394,600), phase-in windows (Single $50K, MFJ $100K), W-2/UBIA limits (50%/25%/2.5%) all match.

#### ⚠️ DISPUTED — Shaw Decision Required:
| # | Item | Ours | OA | Analysis | Shaw Decision |
|---|---|---|---|---|---|
| Q1 | MFS phase-in window | $50,000 | $25,000 | IRC 199A(e)(2)(B) says "$50,000 for taxpayer other than joint return" — MFS IS "other than joint." Our value appears correct per statutory text. OA's $25,000 may be an error. | ☐ ACCEPT_OURS / ☐ ACCEPT_OA / ☐ NEEDS_RESEARCH |
| Q2 | MFS upper limit | $247,300 | $222,300 | Follows from Q1 ($197,300 + phase-in) | ☐ (follows Q1) |

#### 🔴 Missing Items (auto-fix from OA):
| # | Item | OA Detail | Status |
|---|---|---|---|
| Q3 | OBBBA 23% rate for 2026+ | OBBBA P.L. 119-21 raised QBI to 23% starting 2026 | AUTO-FIX (add to 2026 data) |
| Q4 | SSTB classification rules | 11-row determination table + de minimis (10%/5%) | AUTO-FIX |
| Q5 | Circular dependency resolution | Iterative computation order (QBI↔retirement↔SE health) | AUTO-FIX |
| Q6 | Form 8995 line-by-line (14 lines) | Simplified computation walkthrough | AUTO-FIX |
| Q7 | Form 8995-A structure (Schedules A-D) | Detailed computation form | AUTO-FIX |
| Q8 | QBI loss carryover rules | IRC 199A(c)(2), Form 8995 line 13 | AUTO-FIX |
| Q9 | QBI computation formula | Schedule C net - ½SE - SE health - retirement | AUTO-FIX |
| Q10 | Conservative defaults (9 rules) | Fallback behaviors for ambiguity | AUTO-FIX |
| Q11 | Reviewer attention thresholds (9 triggers) | "TI within $10K of threshold" etc. | AUTO-FIX |
| Q12 | Taxable income cap as structured field | 20% of TI excl. net capital gain | AUTO-FIX |
| Q13 | SE cross-reference (15.3%, 92.35%) | In QBI context | AUTO-FIX |
| Q14 | Worked examples (3) + test suite (6 cases) | Dollar-exact computations | AUTO-FIX |

### 1.4 Capital Gains & NIIT

**Result: 11 ✅ Match | 4 🔴 Missing | 0 ⚠️ | 9 ℹ️ OA Lacks**

All overlapping LTCG brackets (Single/MFJ 0%/15%/20%) and NIIT (3.8%, $200K/$250K) match exactly.

#### 🔴 Missing Items:
| # | Item | OA Value | Status |
|---|---|---|---|
| C1 | Collectibles rate (28%) | IRC 408(m), IRS Notice 2023-27 (NFTs) | AUTO-FIX |
| C2 | Wash sale rules for crypto | IRC 1091 does NOT apply to crypto (2025) | AUTO-FIX |
| C3 | Form 8949 Box A/B/C classification | 1099 basis reporting categories | AUTO-FIX |
| C4 | Form 1099-DA requirements | TD 9877, effective Jan 1, 2025 | AUTO-FIX |

### 1.5 FEIE (Foreign Earned Income Exclusion)

**Result: 4 ✅ Match | 6 🔴 Missing | 0 ⚠️ | 1 ℹ️ OA Lacks (entire module)**

Our values match IRS official ($130,000 exclusion, 330 days, 12 months, $39,000 housing limit).

#### 🔴 Missing Items (IRS cross-check, no OA source):
| # | Item | IRS Value | Status |
|---|---|---|---|
| E1 | Housing exclusion base amount | 16% of $130,000 = $20,800 | AUTO-FIX |
| E2 | Housing deduction (self-employed) vs exclusion (employee) | Distinct provisions | AUTO-FIX |
| E3 | High-cost area adjustments | Published per-city limits | NEEDS_RESEARCH |
| E4 | Prorated exclusion for partial year | Days / 365 | AUTO-FIX |
| E5 | Bona fide residence test | Alternative to physical presence | AUTO-FIX |
| E6 | Earned income definition/limits | What qualifies as "foreign earned" | AUTO-FIX |

---

## Part 2: State Tax Audit — CA & NY (Priority States)

### 2.1 California

**Result: 9 rates ✅ | 26 threshold ⚠️ (systematic ~3%) | 9 🔴 Missing | 2 ℹ️ OA Lacks**

All 9 bracket rates match (1% → 12.3%). All threshold values differ by ~3% — **our values are consistently higher**. Root cause: OA marks all brackets "(verify 2025)" = projected estimates. Our data cites `ca_2025_540_tax_rate_schedules` (actual FTB publication).

**OA incorrectly merges HOH with Single** — we correctly have a separate HOH schedule with wider thresholds.

#### ⚠️ CA Threshold Discrepancies (systematic):

| Bracket | Our Single | OA Single | Delta | Analysis |
|---|---|---|---|---|
| 1% | $11,079 | $10,756 | +$323 | OA projected |
| 2% | $26,264 | $25,499 | +$765 | OA projected |
| 4% | $41,452 | $40,245 | +$1,207 | OA projected |
| ... | ... | ... | ~3% | All consistent |
| Std Ded (S) | $5,706 | $5,540 | +$166 | OA projected |

**Recommendation:** Verify our `source_id: ca_2025_540_tax_rate_schedules` against actual FTB publication. If confirmed, **ACCEPT_OURS** for all 26 items.

| # | Shaw Decision |
|---|---|
| CA1 | ☐ ACCEPT_OURS (our FTB source confirmed) / ☐ NEEDS_RESEARCH |

#### 🔴 Missing Items:
| # | Item | OA Detail | Status |
|---|---|---|---|
| CA2 | MHST surcharge | +1% above $1M, not indexed, not doubled for MFJ | AUTO-FIX |
| CA3 | Personal exemption credits | $144(S/MFS), $288(MFJ/QSS), $433/dependent | AUTO-FIX |
| CA4 | Renter's credit | $60(S)/$120(MFJ), AGI limits $50,746/$101,492 | AUTO-FIX |
| CA5 | CalEITC | Max earned income $30,950, max ~$3,529 | AUTO-FIX |
| CA6 | Young Child Tax Credit (YCTC) | $1,117 per child under 6 | AUTO-FIX |
| CA7 | SDI/VPDI deduction | 1.1% rate, $153,164 wage ceiling | AUTO-FIX |
| CA8 | California AMT | 7% flat rate | AUTO-FIX |
| CA9 | Schedule CA adjustments | OBBBA decoupling, QBI add-back, HSA add-back | AUTO-FIX |

### 2.2 New York

**Result: 50 ✅ Match | 0 ⚠️ | 13 🔴 Missing | 0 ℹ️ OA Lacks**

**Perfect match** — all 45 bracket values (9 tiers × 5 filing statuses) and 5 standard deductions match exactly.

#### 🔴 Missing Items:
| # | Item | OA Detail | Impact | Status |
|---|---|---|---|---|
| NY1 | NYC local tax | 4 brackets (3.078%-3.876%) by filing status | **~3-4% understatement for NYC residents** | AUTO-FIX |
| NY2 | Yonkers resident surcharge | 16.75% of state tax | Material for Yonkers | AUTO-FIX |
| NY3 | Yonkers nonresident earnings | 0.5% minus $3,000 exemption | | AUTO-FIX |
| NY4 | MCTMT | 0.60% Zone 1 / 0.34% Zone 2 (SE >$50K) | | AUTO-FIX |
| NY5 | $107,650 recapture | Phases out bracket benefits for high earners | Acknowledged in notes | AUTO-FIX |
| NY6 | Dependent exemption | $1,000 per dependent | | AUTO-FIX |
| NY7 | Dependent standard deduction | $3,100 | | AUTO-FIX |
| NY8 | Pension/annuity exclusion | Up to $20,000 (age 59.5+) | | AUTO-FIX |
| NY9-13 | NYC credits, NY EIC, Empire State Child Credit, IT-225/IT-558 | Various | | AUTO-FIX |

---

## Part 3: Remaining 49 States — Discrepancies

### ⚠️ STRUCTURAL ERRORS (tax_base wrong) — Shaw Decision Required

These are computation-chain errors where the wrong starting point is used.

| # | State | Our tax_base | Correct (per OA) | Impact | Shaw Decision |
|---|---|---|---|---|---|
| S1 | VT | federal_agi | federal_taxable_income | VT piggybacks FTI; our std_deduction field should not exist | ☐ FIX |
| S2 | MN | federal_agi | federal_taxable_income | Structural mismatch; std_deduction may be double-counted | ☐ FIX |
| S3 | MS | federal_agi | Independent computation | MS does NOT start from federal AGI | ☐ FIX |
| S4 | OR | federal_agi | federal_taxable_income | OR starts from FTI (Line 15) | ☐ FIX |
| S5 | CO | qbi_addback: true | QBI already deducted in FTI | Flag is architecturally wrong | ☐ FIX |

### ⚠️ BRACKET THRESHOLD ERRORS — Shaw Decision Required

| # | State | Issue | Our Value | OA Value | Shaw Decision |
|---|---|---|---|---|---|
| S6 | VT MFS | Copies Single instead of half-MFJ | $47,900/$116,350/$242,000 | $39,975/$96,650/$147,300 | ☐ ACCEPT_OA |
| S7 | VT HoH | All 3 thresholds wrong | $64,000/$153,800/$240,800 | $64,200/$165,700/$268,300 | ☐ ACCEPT_OA |
| S8 | VT Single B2 | Minor rounding | $116,350 | $116,000 | ☐ ACCEPT_OA |
| S9 | VT Std Ded | Should not exist (FTI start) | $12,950/$25,900/... | N/A (remove) | ☐ REMOVE |
| S10 | ND MFJ | Mechanically doubled from Single | $96,950/$489,650 | $80,975/$298,075 | ☐ ACCEPT_OA |
| S11 | ND MFS | Mechanically copied from Single | $48,475/$244,825 | $40,475/$149,025 | ☐ ACCEPT_OA |
| S12 | ND HoH | Mechanically derived (1.5x Single) | $72,713/$367,238 | $64,950/$271,450 | ☐ ACCEPT_OA |
| S13 | NM Single | Intermediate thresholds shifted | $11,000 at B2 | $16,500 at B2 | ☐ ACCEPT_OA |
| S14 | NM MFJ | Intermediate thresholds shifted | $16,000 at B2 | $25,000 at B2 | ☐ ACCEPT_OA |
| S15 | NM MFS | Uses Single instead of own schedule | $5,500/$11,000/... | $4,000/$12,500/$25,000/$50,000/$157,500 | ☐ ACCEPT_OA |
| S16 | WI B2 upper | All filing statuses wrong | S:$29,370 MFJ:$39,150 MFS:$19,580 | S:$50,480 MFJ:$67,300 MFS:$33,650 | ☐ ACCEPT_OA |
| S17 | AL HOH | Uses MFJ thresholds instead of Single | $1,000/$6,000 | $500/$3,000 (Single schedule) | ☐ ACCEPT_OA |
| S18 | AR all | Every threshold off by $100-700 | $5,599/$11,199/... | $5,499/$10,899/... | ☐ NEEDS_RESEARCH |
| S19 | OK MFJ top | Top bracket start | $12,200 | $14,400 | ☐ ACCEPT_OA |
| S20 | MT HoH | Threshold | $30,750 | $31,700 | ☐ ACCEPT_OA |

### ⚠️ RATE & DEDUCTION ERRORS — Shaw Decision Required

| # | State | Issue | Our Value | OA Value | Shaw Decision |
|---|---|---|---|---|---|
| S21 | IN rate | Flat rate for TY2025 | 3.00% | 3.05% | ☐ NEEDS_RESEARCH |
| S22 | IL exemption | Personal exemption | $2,850 | $2,625 | ☐ NEEDS_RESEARCH |
| S23 | IN dependent | Dependent exemption | $3,000 | $1,500 | ☐ NEEDS_RESEARCH |
| S24 | VA std ded | Uses 2026 values in 2025 file | $9,680/$19,360 | $9,430/$18,860 (2025 combined) | ☐ FIX (use 2025) |
| S25 | MS HOH PE | Personal exemption | $6,000 | $8,000 | ☐ ACCEPT_OA |
| S26 | OH PE | Personal exemption (modeled as std ded) | $1,850 | $1,900 | ☐ ACCEPT_OA |
| S27 | NE PE credit | Exemption credit | $171 | $157 | ☐ NEEDS_RESEARCH |
| S28 | WV MFS | Same brackets for all vs halved for MFS | Uniform | Halved ($5K/$12.5K/$20K/$30K) | ☐ ACCEPT_OA |
| S29 | ME surcharge | Missing 4th bracket | 3 brackets | 4th: 9.15% above $1M | ☐ AUTO-FIX |

---

## Part 4: States — Full Match (No Issues)

These states had **zero discrepancies** (brackets + deductions all match):

| State | Type | Notes |
|---|---|---|
| AK | No income tax | Confirmed |
| CT | 7 brackets × 4 statuses | All match |
| DC | 7 brackets | All match + std deduction match |
| DE | 7 brackets | All match + std deduction match |
| FL | No income tax | Confirmed |
| GA | Flat 5.19% | Rate + std deduction match |
| HI | 12 brackets (Single/MFJ/MFS) | All match (HOH not in OA) |
| KS | 2 brackets | Match (combined std ded decomposition verified) |
| KY | Flat 4.0% | Rate + std deduction match |
| LA | Flat 3.0% | Rate + std deduction match |
| MA | Flat 5.0% + 4% surtax | Rate + surtax threshold + exemptions match |
| MD | 10 brackets × 4 statuses | All match (combined std ded decomposition verified) |
| MI | Flat 4.25% | Rate + exemption match |
| MO | 8 brackets | All match |
| NC | Flat 4.25% | Rate + std deduction all 4 statuses match |
| NE | 4 brackets (Single/MFJ/HoH) | All match |
| NH | No income tax | Confirmed (I&D repealed 2025) |
| NJ | 7-8 brackets | All match |
| NV | No income tax | Confirmed |
| OH | 3 brackets | Match (exemption issue separate) |
| OK | 6 brackets (Single) | Match (MFJ top bracket issue separate) |
| OR | 4 brackets × 4 statuses | All match + std deduction match |
| PA | Flat 3.07% | Match |
| RI | 3 brackets | Match (combined std ded decomposition verified) |
| SC | 3 brackets | Near-match ($10 rounding) |
| SD | No income tax | Confirmed |
| TN | No income tax | Confirmed |
| TX | No income tax | Confirmed |
| UT | Flat 4.5% | Match (credit structure acknowledged) |
| WA | No income tax | Confirmed (cap gains modeled) |
| WY | No income tax | Confirmed |

---

## Part 5: Missing Items Summary (🔴 Auto-Fix Candidates)

### High Priority (affects calculation accuracy)
1. **ME 2% surcharge** above $1M — missing 4th bracket
2. **NY NYC local tax** — ~3-4% understatement for NYC residents
3. **CA MHST** +1% above $1M — acknowledged but not modeled
4. **NM standard deduction** — entirely missing
5. **IA standard deduction** — entirely missing
6. **ID standard deduction** — entirely missing
7. **MO standard deduction** — entirely missing (MO-specific, not federal conformity)
8. **MO federal income tax deduction** — unique MO feature, up to $5K/$10K
9. **MO 100% capital gains subtraction** — effective TY 2025
10. **MT preferential capital gains rates** — 3.0%/4.1%
11. **MA Part C rate** — 8.5% on short-term capital gains

### Medium Priority (affects completeness)
12-31. Various state credits/exemptions (CalEITC, YCTC, renter's credits, dependent exemptions, pension exclusions, etc.)
32-38. Federal: FICA optional methods, QBI SSTB rules, collectibles 28%, Form 8949, FEIE housing details

### Low Priority (informational/future)
39+. Form mappings, worked examples, conservative defaults, refusal catalogues

---

## Part 6: Shaw Decision — 以 OpenAccountants 为主

> **Decision date:** 2026-06-09
> **Rule:** All discrepancies resolved in favor of OpenAccountants values.
> **Exception:** CA bracket thresholds — OA self-marks as "(verify 2025)" projected; our FTB-sourced values likely more accurate. Adopt OA for now, flag for FTB verification.

### All 23 ⚠️ Items → ACCEPT_OA

| # | Item | Action | New Value |
|---|---|---|---|
| Q1 | QBI MFS phase-in | ACCEPT_OA | $25,000 |
| Q2 | QBI MFS upper limit | ACCEPT_OA | $222,300 |
| S1 | VT tax_base | FIX → federal_taxable_income | Remove std_deduction field |
| S2 | MN tax_base | FIX → federal_taxable_income | Review std_deduction field |
| S3 | MS tax_base | FIX → independent_computation | Review start_from |
| S4 | OR tax_base | FIX → federal_taxable_income | Keep std_deduction |
| S5 | CO qbi_addback | REMOVE flag | qbi_addback: false or remove |
| S6 | VT MFS brackets | ACCEPT_OA | $39,975/$96,650/$147,300 |
| S7 | VT HoH brackets | ACCEPT_OA | $64,200/$165,700/$268,300 |
| S8 | VT Single B2 | ACCEPT_OA | $116,000 |
| S9 | VT Std Ded | REMOVE | N/A (FTI start = no separate std ded) |
| S10 | ND MFJ brackets | ACCEPT_OA | $80,975/$298,075 |
| S11 | ND MFS brackets | ACCEPT_OA | $40,475/$149,025 |
| S12 | ND HoH brackets | ACCEPT_OA | $64,950/$271,450 |
| S13 | NM Single brackets | ACCEPT_OA | $5,500/$16,500/$33,500/$66,500/$210,000 |
| S14 | NM MFJ brackets | ACCEPT_OA | $8,000/$25,000/$50,000/$100,000/$315,000 |
| S15 | NM MFS brackets | ACCEPT_OA | $4,000/$12,500/$25,000/$50,000/$157,500 |
| S16 | WI B2 thresholds | ACCEPT_OA | S:$50,480 MFJ:$67,300 MFS:$33,650 |
| S17 | AL HOH brackets | ACCEPT_OA → use Single schedule | $500/$3,000 |
| S18 | AR brackets | ACCEPT_OA | $5,499/$10,899/$15,599/$25,699 |
| S19 | OK MFJ top bracket | ACCEPT_OA | $14,400 |
| S20 | MT HoH threshold | ACCEPT_OA | $31,700 |
| S21 | IN rate | ACCEPT_OA | 3.05% |
| S22 | IL exemption | ACCEPT_OA | $2,625 |
| S23 | IN dependent exemption | ACCEPT_OA | $1,500 |
| S24 | VA std deduction | ACCEPT_OA | S:$9,430 MFJ:$18,860 (2025 combined) |
| S25 | MS HOH PE | ACCEPT_OA | $8,000 |
| S26 | OH PE | ACCEPT_OA | $1,900 |
| S27 | NE PE credit | ACCEPT_OA | $157 |
| S28 | WV MFS brackets | ACCEPT_OA | Halved: $5K/$12.5K/$20K/$30K |
| S29 | ME surcharge | ADD | 4th bracket: 9.15% above $1M |
| CA1 | CA thresholds | ACCEPT_OA (flagged for FTB verify) | OA projected values |

### Codex PR Scope

**PR 1 — Data fixes (high priority):**
- `data/tax_years/2025/us_states.json`: Fix all 29 state discrepancy items above
- `data/tax_years/2025/us_qbi.json`: Fix MFS phase-in to $25,000, upper limit to $222,300

**PR 2 — Missing data enrichment (medium priority):**
- `data/tax_years/2025/us_fica.json`: Add 7 missing fields (F1-F7)
- `data/tax_years/2025/us_capital_gains.json`: Add collectibles_rate: 0.28
- `data/tax_years/2025/us_feie.json`: Add 6 missing fields (E1-E6)
- `data/tax_years/2025/us_states.json`: Add missing state items (ME surcharge, NY NYC tax, etc.)

**PR 3 — QBI enrichment (lower priority):**
- `data/tax_years/2025/us_qbi.json`: Add SSTB rules, form mappings, loss carryover (Q3-Q14)

---

## Appendix: Methodology

- **Federal audit:** 5 parallel agents, each reading one `us_*.json` + corresponding OA federal `.md` files
- **CA/NY audit:** 2 dedicated agents with deep line-by-line comparison
- **Remaining 49 states:** 5 batch agents (10 states each), reading `us_states.json` + each state's OA `.md` file
- **Comparison standard:** Exact value match required. Combined fields (std_deduction + personal_exemption) decomposed and verified.
- **OA data quality notes:** Some OA state files use "(verify 2025)" markers = projected/estimated figures. Where our data cites actual state DOR publications, ours is likely more authoritative for those specific values.
