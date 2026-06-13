# Design Spec: Tax Skill Integration & Engine Refactoring

> Date: 2026-06-09
> Author: Claude (brainstorming skill)
> Approved by: Shaw (verbal confirmation, same session)
> Status: Approved, pending implementation

---

## 1. Context & Motivation

We installed 6 tax/finance professional Claude Code skills:

| Skill | Source | Files | License |
|---|---|---|---|
| `us-federal-tax-assistant` | calef/us-federal-tax-assistant-skill | 3 | GPL v3 |
| `tax-organizer` | elderengineer/tax-organizer | 5 | MIT |
| `openaccountants` | openaccountants/openaccountants | 215 | AGPL-3.0 |
| `tax-prep-beancount` | dcposch gist | 1 | None |
| `finance-compliance` | JoelLewis/finance_skills | 16 | MIT |
| `finance-wealth-mgmt` | JoelLewis/finance_skills | 32 | MIT |

These skills contain detailed, research-verified US tax rules with IRC citations, exact 2025 figures, and 51-state coverage. The question: how to leverage them for TaxGlobal AI.

## 2. Decision: Priority C → A → B

Shaw decided the integration priority:

1. **C: Development efficiency + quality assurance** — cross-validate our engine data against openaccountants' authoritative rules
2. **A: Knowledge base enrichment** — feed all 215 .md files into GraphRAG (Neo4j + Chroma)
3. **B: New engine skill acceleration** — use skills as reference for implementing roadmap skills #9, #10, #7, #11

## 3. Architecture: Three-Stage Rocket

```
Phase 1: Engine Audit (before M3, ~2 days)
  ├─ Federal modules: brackets/FICA/QBI/capital gains/FEIE
  ├─ 51 state tax full comparison
  ├─ Output: docs/engine_audit_report.md
  ├─ OA has / we don't → auto-fix
  └─ Value discrepancy → Shaw manual review
       ↓ Audit sign-off
Phase 2: GraphRAG Ingestion (~1 day)
  ├─ 215 .md files chunked by ## heading (~500-800 chunks)
  ├─ Neo4j nodes + Chroma vectors (incremental, no overwrite)
  ├─ IRC citation auto-extraction → Source node edges
  ├─ source: "openaccountants" tag for provenance
  └─ Verification: search API returns OA content
       ↓ Ingestion verified
Phase 3: Skill Acceleration (embedded in M3 steps, no extra timeline)
  ├─ M3.6 extract_w2 → ref tax-organizer + us-federal-tax-assistant
  ├─ Codex prompt Pre-read includes skill paths
  ├─ PR review uses skills for cross-validation
  └─ Roadmap update: #9/#10/#4 annotated + #12-14 candidates
       ↓ Normal M3.1 start
```

---

## 4. Phase 1: Engine Audit — Detailed Design

### 4.1 Audit Matrix

| Audit Item | Our Data File | OA Reference File | Comparison Points |
|---|---|---|---|
| Federal brackets | `data/tax_years/2025/us_federal.json` | `us-schedule-c-and-se-computation.md` + foundation | 7 brackets × 4 filing statuses + standard deduction |
| FICA / SE tax | `data/tax_years/2025/us_fica.json` | `us-schedule-c-and-se-computation.md` | SS wage base $176,100, 92.35% factor, 12.4%/2.9%/0.9%, Additional Medicare thresholds |
| QBI §199A | `data/tax_years/2025/us_qbi.json` | `us-qbi-deduction.md` | Thresholds $197,300/$394,600, phase-out $247,300/$494,600, 20% rate |
| Capital gains | `data/tax_years/2025/us_capital_gains.json` | `us-crypto-tax.md` | LTCG 3 brackets × 4 filing statuses + NIIT 3.8% thresholds |
| FEIE | `data/tax_years/2025/us_feie.json` | (No OA skill → IRS official cross-check) | 2025 exclusion $130,000, housing limit |
| 51 state taxes | `data/tax_years/2025/us_states.json` (51 entries) | `us-states/*/` (51 directories) | Per state: rate brackets, standard deduction, surcharges (e.g., CA MHST), exemptions |

### 4.2 Finding Categories

| Category | Symbol | Rule |
|---|---|---|
| Match | ✅ | Both sources agree — no action |
| Missing (we lack) | 🔴 | OA has it, we don't → **auto-fix**: add to our data JSON |
| Discrepancy | ⚠️ | Both have it, values differ → **manual review**: Shaw decides |
| OA lacks | ℹ️ | We have it, OA doesn't → keep ours, note for reference |

### 4.3 Output

- File: `docs/engine_audit_report.md`
- Format per finding:
  ```
  #### [CATEGORY] {Item description}
  Our data: {value}
  OpenAccountants: {value}
  Source: {IRC/IRS/State DOR reference}
  Recommendation: {action}
  Status: {AUTO-FIX | NEEDS_REVIEW | NO_ACTION}
  ```
- Summary section with counts per category
- Shaw reviews ⚠️ items and marks each as ACCEPT_OURS / ACCEPT_OA / NEEDS_RESEARCH

### 4.4 Execution Plan

1. Read all `data/tax_years/2025/*.json` files
2. Read all `openaccountants/federal/*.md` + `openaccountants/us-states/*/*.md` files
3. Cross-compare systematically (parallel agents for 51 states)
4. Generate report
5. Auto-apply 🔴 findings (add missing data to JSON)
6. Present ⚠️ findings for Shaw's manual decision
7. After Shaw signs off → Codex PR for any data file changes

---

## 5. Phase 2: GraphRAG Ingestion — Detailed Design

### 5.1 Data Sources & Chunking Strategy

| Source Directory | Files | Chunking Strategy | Neo4j Node Type |
|---|---|---|---|
| `federal/` | 11 | By `## Section` heading, avg 500-1500 chars per chunk | `TaxRule` → `Jurisdiction(US_FEDERAL)` |
| `us-states/*/` | ~160 | By state + section; tax rate tables kept as intact chunks | `TaxRule` → `Jurisdiction(STATE_XX)` |
| `cross-border/` | 31 | By topic (each .md = one topic) | `TaxRule` → `Topic(CROSS_BORDER)` |
| `foundation/` | 17 | Whole file as one chunk (workflow templates) | `TaxRule` → `Topic(WORKFLOW)` |

### 5.2 Ingestion Pipeline

```
.claude/skills/openaccountants/**/*.md
  ↓
[Chunker] — Split by ## heading + metadata extraction
           — Extract: tax_year, jurisdiction, IRC refs, version
  ↓
[Embedder] — backend/knowledge/embedder.py
           — Model: BAAI/bge-small-zh-v1.5 (local, no data egress)
  ↓
[Neo4j]  — Create TaxRule nodes
         — APPLIES_TO → Jurisdiction edges
         — REFERENCES → Source edges (auto-extracted IRC citations)
         — Tag: source="openaccountants", version=skill_version
[Chroma] — Vector ingestion
         — Metadata: {source, jurisdiction, topic, tax_year}
```

### 5.3 Design Decisions

1. **Provenance tagging**: All OA nodes carry `source: "openaccountants"` — distinct from our hand-authored knowledge. Search API can filter/weight by source.
2. **Incremental, not replacement**: M2.2 existing knowledge nodes untouched. OA content is additive. Same rule from two sources = two nodes (multi-source cross-validation benefits fact-checker).
3. **Dedup strategy**: No dedup at ingestion. Hybrid search scoring naturally handles relevance. Two sources saying the same thing reinforces confidence.
4. **IRC citation extraction**: Regex pattern `IRC \d+[a-z]?(\([a-z0-9]+\))*` to extract IRC references. Each unique citation becomes a `Source` node in Neo4j with edges to all `TaxRule` nodes that reference it. Enables multi-hop reasoning (e.g., "what rules reference IRC 1402?").

### 5.4 Deliverables

- `scripts/ingest_openaccountants.py` — one-time ingestion script (Codex writes, Claude reviews)
- ~500-800 new Neo4j `TaxRule` nodes + related `Source`/`Jurisdiction` edges
- ~500-800 new Chroma vectors
- Verification: `GET /api/knowledge/search?q=California+Mental+Health+Services+Tax` returns OA content

---

## 6. Phase 3: Skill Acceleration — Detailed Design

### 6.1 Skill Mapping

| Roadmap Skill | Reference Claude Code Skill | How to Use | Target Step |
|---|---|---|---|
| #9 `extract_w2` | `tax-organizer` (field mapping) + `us-federal-tax-assistant` (form line numbers) | Codex prompt Pre-read for W-2 Box 1-17 ground truth; DeepSeek Vision output validated against these mappings | M3.6 |
| #10 `generate_form` | `us-federal-tax-assistant` (14-form completion flow + Phase 4 audit cross-check) | Design reference for future form PDF generation; adopt 4-phase architecture (collect → identify → fill → audit) | M4 backlog |
| #4 `track_crypto` enhancement | `tax-prep-beancount` (FIFO lot matching + Form 8949 Box A-F + wash sale + fork/airdrop basis) | Enhance `crypto_gain_estimate` engine function with lot matching, 8949 classification, fork basis rules | M3+ backlog |
| #7 `classify_transaction` | `tax-organizer` (doc classification) + `openaccountants/us-sole-prop-bookkeeping` (transaction → Schedule C line) | Transaction auto-classification to Schedule C line numbers | M4 backlog |
| #11 `check_treaty` | `openaccountants/cross-border/` (31 files: withholding-tax-matrix, FATCA/CRS, tax-residency-planning) | Treaty lookup + FTC calculation; backed by cross-border GraphRAG knowledge | M4 backlog |

### 6.2 Usage Mode

These Claude Code skills do NOT enter product code. They serve three purposes:

1. **Codex prompt writing**: Pre-read paths added to prompts so Codex references correct field mappings and rules
2. **PR review cross-validation**: Claude uses skill data for independent re-derivation of tax amounts
3. **Design doc authoring**: Skill architectures (e.g., us-federal-tax-assistant's 4-phase form workflow) inform our design decisions

### 6.3 Roadmap Updates After Audit

Update `docs/roadmap_skills_status.md`:
- Skill #9 `extract_w2`: annotate reference sources (tax-organizer + us-federal-tax-assistant)
- Skill #10 `generate_form`: annotate reference (us-federal-tax-assistant 4-phase flow)
- Skill #4 `track_crypto`: annotate enhancement direction (FIFO lot matching from tax-prep-beancount)
- Define candidate Skills #12-14 based on openaccountants cross-border + finance-compliance modules

---

## 7. Timeline

| Phase | Duration | Prerequisite | Deliverable |
|---|---|---|---|
| Phase 1: Engine Audit | ~2 days | None | `docs/engine_audit_report.md` + data fixes |
| Phase 1b: Shaw Review | ~0.5 day | Audit report | Shaw signs off on ⚠️ findings |
| Phase 2: GraphRAG Ingestion | ~1 day | Audit signed off | ingestion script + verified search results |
| Phase 3: Skill Acceleration | Ongoing | Ingestion verified | Embedded in M3 Codex prompts |
| M3.1 start | After Phase 2 | All above | Normal M3 development begins |

**Total delay to M3: ~3-4 days. ROI: engine data verified by independent third-party source, knowledge base 3x richer, M3 development faster and more accurate.**

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| openaccountants data has errors | We adopt wrong values | Every 🔴 auto-fix still gets Codex PR + Claude review; borderline cases go to ⚠️ manual |
| GPL v3 / AGPL-3.0 license contamination | Legal risk for commercial product | Skills stay in `.claude/skills/` (dev tooling), never enter product code. GraphRAG ingests factual tax data (tax rates, thresholds, IRC citations — facts are not copyrightable under US law) extracted from skills, not the creative prose itself. Note: this is our engineering position, not legal advice; consult attorney before commercial launch. |
| GraphRAG ingestion quality | Poor chunks = poor search | Chunk by ## heading (semantic boundaries); tax rate tables kept intact; verify with sample queries |
| Audit finds many discrepancies | Blocks M3 for longer | Parallel processing (agents); ⚠️ items can be time-boxed (Shaw reviews top-priority first, rest queued) |

---

## 9. Non-Goals (YAGNI)

- NOT rewriting our engine to use openaccountants' computation logic (we keep our engine, they're just a reference)
- NOT installing openaccountants as a runtime dependency
- NOT building a UI for the audit report (markdown is fine)
- NOT doing 2026 tax year audit now (only 2025; 2026 when OA updates)
- NOT integrating finance-compliance or finance-wealth-mgmt into product now (M5+)
