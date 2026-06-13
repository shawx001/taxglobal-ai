# Tax Skill Integration & Engine Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-validate our 2025 tax engine data against openaccountants' research-verified rules, fix gaps, then ingest 215 skill files into GraphRAG to triple our knowledge base before M3 starts.

**Architecture:** Phase 1 is a pure audit (read our JSON + read OA markdown, compare, produce report). Phase 2 is a one-time ingestion script that chunks OA markdown by heading, embeds locally, and writes to Neo4j + Chroma. Phase 3 is documentation updates only. No product code changes in Phase 1; Phase 2 adds one script under `scripts/`.

**Tech Stack:** Python, existing `backend/knowledge/` (embedder.py, vector_store.py, neo4j_client.py), existing `data/tax_years/2025/*.json`, openaccountants `.claude/skills/openaccountants/**/*.md`.

**Key files referenced:**
- Our data: `data/tax_years/2025/us_federal.json`, `us_fica.json`, `us_qbi.json`, `us_capital_gains.json`, `us_feie.json`, `us_states.json`
- OA federal: `.claude/skills/openaccountants/federal/*.md` (11 files)
- OA states: `.claude/skills/openaccountants/us-states/*/` (51 dirs, ~160 files)
- OA cross-border: `.claude/skills/openaccountants/cross-border/*.md` (31 files)
- OA foundation: `.claude/skills/openaccountants/foundation/*.md` (17 files)

---

## Phase 1: Engine Audit

Phase 1 is performed entirely by Claude (not Codex). It is a manual, thorough cross-comparison between our engine data files and the openaccountants skill files. The output is `docs/engine_audit_report.md`.

**Important:** This phase involves reading files and writing a report. There are no code changes, no tests to run, no commits. The "steps" below are the sequential comparison tasks.

---

### Task 1: Audit Federal Income Tax Brackets

**Files:**
- Read: `data/tax_years/2025/us_federal.json` (lines 1-59, `ordinary_income_brackets` + `standard_deduction`)
- Read: `.claude/skills/openaccountants/federal/us-schedule-c-and-se-computation.md` (for any bracket references)
- Read: `.claude/skills/openaccountants/federal/us-qbi-deduction.md` (§2 references federal brackets in taxable-income context)

- [ ] **Step 1: Extract our federal brackets**

Read `data/tax_years/2025/us_federal.json`. Record all values:
- `standard_deduction`: single, mfs, mfj, qss, hoh
- `ordinary_income_brackets`: all 7 brackets × 4 filing statuses (single, mfj, hoh, mfs)
- Note the `source_ids` and `citation` for each

- [ ] **Step 2: Extract OA federal figures**

Read all OA federal skills. The primary bracket reference is in `us-schedule-c-and-se-computation.md` and `us-qbi-deduction.md` (since QBI uses taxable income thresholds that align with bracket boundaries). OA may not have a dedicated "federal brackets" file — if so, note as `ℹ️ OA lacks`.

Also check `us-tax-workflow-base.md` in `foundation/` for any federal bracket tables.

- [ ] **Step 3: Compare and record findings**

For each value: if match → ✅. If our data missing something OA has → 🔴. If values differ → ⚠️. If OA doesn't have it → ℹ️.

Write findings to a scratch section for later assembly into the final report.

---

### Task 2: Audit FICA / Self-Employment Tax

**Files:**
- Read: `data/tax_years/2025/us_fica.json` (47 lines)
- Read: `.claude/skills/openaccountants/federal/us-schedule-c-and-se-computation.md` (Section 1 — Quick Reference, has exact FICA/SE figures)

- [ ] **Step 1: Extract our FICA data**

From `us_fica.json`, record:
- `social_security.wage_base` (expect 176100)
- `social_security.self_employment_combined_rate` (expect 0.124)
- `social_security.employee_rate` / `employer_rate` (expect 0.062 each)
- `medicare.self_employment_combined_rate` (expect 0.029)
- `medicare.employee_rate` / `employer_rate` (expect 0.0145 each)
- `additional_medicare.employee_rate` (expect 0.009)
- `additional_medicare.taxpayer_thresholds` (single: 200000, mfj: 250000, mfs: 125000, hoh: 200000, qss: 200000)
- `self_employment.net_earnings_multiplier` (expect 0.9235)

- [ ] **Step 2: Extract OA FICA/SE data**

From `us-schedule-c-and-se-computation.md` Section 1, record the "Self-Employment Tax Core Figures (TY2025)" table:
- Net SE earnings adjustment factor (92.35%)
- OASDI rate (12.4%)
- Medicare rate (2.9%)
- Combined SE tax rate (15.3%)
- Social Security wage base ($176,100)
- Additional Medicare Tax rate (0.9%)
- Additional Medicare Tax thresholds (single/HoH/QSS: $200,000; MFJ: $250,000; MFS: $125,000)
- Minimum net SE earnings ($400)
- Deductible portion of SE tax (50%)

- [ ] **Step 3: Compare and record findings**

Cross-compare every value. Pay special attention to:
- Do we have the `$400 minimum SE threshold`? (OA has it — likely 🔴 if we don't)
- Do we have the `50% deductible SE tax` rule in data? (may be in engine logic rather than data)
- Do we have the `15.3% combined rate`? (may be computed, not stored)

---

### Task 3: Audit QBI §199A

**Files:**
- Read: `data/tax_years/2025/us_qbi.json` (45 lines)
- Read: `.claude/skills/openaccountants/federal/us-qbi-deduction.md` (full file)

- [ ] **Step 1: Extract our QBI data**

From `us_qbi.json`, record:
- `qbi_deduction.rate` (expect 0.2)
- `taxable_income_threshold`: single/hoh/mfs/qss (197300), mfj (394600)
- `phase_in_window`: single/hoh/mfs/qss (50000), mfj (100000)
- `upper_limit`: single/hoh/mfs/qss (247300), mfj (494600)
- `wage_ubia_limit`: half_w2_wages_rate (0.5), quarter_w2_wages_rate (0.25), ubia_rate (0.025)

- [ ] **Step 2: Extract OA QBI data**

From `us-qbi-deduction.md`, find Section 3 (year-specific figures table). Record:
- 20% rate (2025), 23% rate (2026+ per OBBBA)
- Thresholds: $197,300 single / $394,600 MFJ
- Phase-in ranges: $50,000 / $100,000
- Upper limits: $247,300 / $494,600
- W-2/UBIA limits: 50% W-2, or 25% W-2 + 2.5% UBIA
- Any SSTB-specific rules or thresholds

- [ ] **Step 3: Compare and record findings**

Special attention:
- OA mentions OBBBA making §199A permanent and raising to 23% for 2026+. Check if our 2026 QBI data (if any) reflects this.
- OA mentions the circular dependency between QBI, retirement, and SE health insurance. Note this for backlog.

---

### Task 4: Audit Capital Gains & NIIT

**Files:**
- Read: `data/tax_years/2025/us_capital_gains.json` (63 lines)
- Read: `.claude/skills/openaccountants/federal/us-crypto-tax.md` (Section 2+)

- [ ] **Step 1: Extract our capital gains data**

From `us_capital_gains.json`, record:
- `long_term_capital_gains.brackets`: 3 brackets (0%, 15%, 20%) × 5 filing statuses
- `net_investment_income_tax.rate` (0.038)
- `net_investment_income_tax.magi_thresholds`: single (200000), hoh (200000), mfj (250000), qss (250000), mfs (125000)
- Short-term treatment: ordinary_income

- [ ] **Step 2: Extract OA capital gains data**

From `us-crypto-tax.md`, find capital gains rate references. OA may reference the same Rev. Proc. 2024-40 brackets. Also check for:
- Collectibles rate (28%) — relevant for NFTs
- §1202 QSBS exclusion rates
- Unrecaptured §1250 gain (25%)

- [ ] **Step 3: Compare and record findings**

Special attention:
- Do we have the collectibles rate (28%)? OA crypto skill mentions NFTs as collectibles.
- Do we have unrecaptured §1250 gain (25%)? Probably 🔴 missing.

---

### Task 5: Audit FEIE

**Files:**
- Read: `data/tax_years/2025/us_feie.json` (18 lines)
- No OA skill for FEIE — cross-check against IRS official figures

- [ ] **Step 1: Extract our FEIE data**

From `us_feie.json`, record:
- `maximum_exclusion` (130000)
- `physical_presence_days` (330)
- `physical_presence_period_months` (12)
- `housing_expense_general_limit` (39000)

- [ ] **Step 2: Cross-check against IRS**

OA does not have a dedicated FEIE skill. Verify our figures against IRS Form 2555 instructions for 2025:
- 2025 maximum exclusion: $130,000 (Rev. Proc. 2024-40)
- Housing exclusion base: 16% of exclusion amount per day × days = $130,000 × 0.16 = $20,800 base
- Housing exclusion general limit: 30% of exclusion = $39,000 (varies by location)

- [ ] **Step 3: Record findings**

Mark as ℹ️ (OA lacks) with IRS cross-check results.

---

### Task 6: Audit State Taxes — California (CA)

**Files:**
- Read: `data/tax_years/2025/us_states.json` → CA section
- Read: `.claude/skills/openaccountants/us-states/ca/ca-income-tax.md`

- [ ] **Step 1: Extract our CA data**

From `us_states.json` CA entry:
- 9 brackets × 5 filing statuses (single, mfs, mfj, qss, hoh)
- Standard deduction: single/mfs ($5,706), mfj/qss ($11,412), hoh ($11,412)
- `tax_base.start_from`: "federal_agi"
- `tax_base.allows_qbi`: false
- `tax_base.capital_gains_treatment`: "ordinary_income"
- Notes about MHST not modeled

- [ ] **Step 2: Extract OA CA data**

From `ca-income-tax.md` Section 3, record:
- 9 brackets (single): 1% up to $10,756 ... 12.3% above $721,315
- MHST: +1% above $1,000,000 (making effective top rate 13.3%)
- Standard deduction: Single/MFS $5,540; MFJ/QSS/HOH $11,080
- Personal exemption credit: Single/MFS $144; MFJ/QSS $288; Dependent $433
- Renter's credit: $60/$120 with CA AGI limits
- CalEITC: max earned income $30,950, max credit ~$3,529
- Young Child Tax Credit: $1,117 per qualifying child under 6

- [ ] **Step 3: Compare and record findings**

**Critical comparisons:**
- **Bracket thresholds**: Our single bracket 1 is "up_to: 11079" vs OA "$10,756". This is likely a ⚠️ DISCREPANCY — one of us may have the wrong year's brackets. Cross-check against FTB 2025 Form 540.
- **Standard deduction**: Our single is $5,706 vs OA $5,540. Another ⚠️ DISCREPANCY.
- **MHST**: Our notes say "1% Mental Health Services Tax over $1,000,000 not modeled (MVP estimate)." OA has it. This is 🔴 MISSING — should be added.
- **Personal exemption credit**: OA has it ($144/$288/$433), we don't. 🔴 MISSING.
- **Renter's credit, CalEITC, YCTC**: OA has them, we don't. 🔴 MISSING (but may be out of MVP scope — note for backlog).

**Note on bracket discrepancy:** OA marks its CA figures as "(verify 2025)" — meaning they may be projected, not final. Our data cites "ca_2025_540_tax_rate_schedules" which is presumably the official FTB publication. This discrepancy MUST go to ⚠️ manual review with official FTB source verification.

---

### Task 7: Audit State Taxes — New York (NY)

**Files:**
- Read: `data/tax_years/2025/us_states.json` → NY section
- Read: `.claude/skills/openaccountants/us-states/ny/ny-income-tax.md`

- [ ] **Step 1: Extract our NY data**

From `us_states.json` NY entry: brackets, standard deduction, filing status specifics.

- [ ] **Step 2: Extract OA NY data**

From `ny-income-tax.md` Section 3:
- 9 brackets (single): 4% up to $8,500 ... 10.9% above $25,000,000
- Standard deduction: Single $8,000, MFJ $16,050, HOH $11,200, MFS $8,000, Dependent $3,100
- $107,650 recapture worksheet threshold
- NYC resident tax: 4 brackets (3.078% to 3.876%)
- Yonkers surcharge: 16.75% of state tax
- MCTMT: 0.60% Zone 1, 0.34% Zone 2 (above $50,000)

- [ ] **Step 3: Compare and record findings**

Special attention:
- Do we model NYC local tax? (likely 🔴 MISSING — most NY filers are NYC residents)
- Do we have the $107,650 recapture mechanism? (likely 🔴 MISSING)
- NY standard deduction: verify our values match OA's $8,000/$16,050/$11,200

---

### Task 8: Audit State Taxes — Remaining 49 States

**Files:**
- Read: `data/tax_years/2025/us_states.json` → each state section
- Read: `.claude/skills/openaccountants/us-states/*/` → each state's income tax .md

- [ ] **Step 1: Categorize states by type**

Group the 51 jurisdictions into audit categories:
1. **No income tax** (9): AK, FL, NV, NH, SD, TN, TX, WA, WY — verify both we and OA agree these have no personal income tax (NH/TN may have interest/dividend tax; WA has capital gains tax)
2. **Flat tax** (~12): CO, IL, IN, KY, MA, MI, NC, PA, UT, etc. — compare single rate + any quirks
3. **Progressive tax** (~25): AZ, AR, CT, GA, HI, ID, IA, KS, LA, ME, MD, MN, MS, MO, MT, NE, NJ, NM, NY, ND, OH, OK, OR, SC, VT, VA, WV, WI, DC — compare full bracket tables
4. **Special cases**: WA (capital gains excise tax, not traditional income tax), NH (interest/dividends only through 2024)

- [ ] **Step 2: Audit each state systematically**

For each state, compare:
- Tax type (progressive/flat/none) — must match
- Bracket thresholds and rates (for progressive states)
- Standard deduction amounts and filing status variations
- Tax base starting point (federal AGI, federal taxable income, state-specific)
- QBI conformity (does state allow §199A?)
- Capital gains treatment (ordinary income vs. preferential)
- Any surcharges or local taxes (NYC, Portland Metro, etc.)
- Source citations

- [ ] **Step 3: Record findings per state**

For each of 51 jurisdictions, produce a finding entry. States where OA has an income tax skill but we only have basic brackets = likely 🔴 for missing features (credits, surcharges, exemptions). States where OA has no income tax skill but we have data = ℹ️.

**Note:** OA has detailed income tax skills only for states with significant complexity (CA, NY, etc.). For simpler states (flat tax, no-income-tax), OA may only have sales tax or franchise tax skills. In those cases, our comparison is limited to confirming the basic rate/bracket match.

---

### Task 9: Assemble Audit Report

**Files:**
- Create: `docs/engine_audit_report.md`

- [ ] **Step 1: Write report header and summary**

```markdown
# Engine Audit Report — 2025 Tax Year

> Generated: 2026-06-09
> Method: Cross-comparison of `data/tax_years/2025/*.json` against openaccountants research-verified skills
> Auditor: Claude (automated cross-reference)

## Summary

| Category | Count | Description |
|---|---|---|
| ✅ Match | N | Both sources agree |
| 🔴 Missing | N | OA has, we lack — auto-fix candidates |
| ⚠️ Discrepancy | N | Both have, values differ — Shaw manual review |
| ℹ️ OA Lacks | N | We have, OA doesn't — keep ours |
```

- [ ] **Step 2: Write federal findings section**

Assemble all findings from Tasks 1-5 (brackets, FICA, QBI, cap gains, FEIE) into the report under `## Federal Modules`.

- [ ] **Step 3: Write state findings section**

Assemble all findings from Tasks 6-8 (CA, NY, remaining 49) into the report under `## State Taxes`. Group by finding category for easy review.

- [ ] **Step 4: Write recommendations section**

List all 🔴 items with specific JSON changes needed. List all ⚠️ items with both values and request Shaw's decision. Example:

```markdown
## Action Items

### Auto-Fix (🔴 Missing — openaccountants has, we lack)
1. CA MHST: Add `"mental_health_services_tax": {"threshold": 1000000, "rate": 0.01}` to CA entry
2. ...

### Manual Review (⚠️ Discrepancy — Shaw decides)
1. CA single bracket 1: Our $11,079 vs OA $10,756. Official FTB source needed.
   → ACCEPT_OURS / ACCEPT_OA / NEEDS_RESEARCH
2. ...
```

- [ ] **Step 5: Present report to Shaw**

Show the summary counts and the ⚠️ items that need manual decision. Wait for Shaw's sign-off before proceeding to Phase 2.

---

## Phase 2: GraphRAG Ingestion

Phase 2 creates a one-time Python script to ingest openaccountants .md files into our existing Neo4j + Chroma knowledge stores. This is a Codex task.

---

### Task 10: Write Ingestion Script — Chunker

**Files:**
- Create: `scripts/ingest_openaccountants.py`
- Reference: `backend/knowledge/embedder.py`, `backend/knowledge/vector_store.py`, `backend/knowledge/neo4j_client.py`

- [ ] **Step 1: Write the chunker function**

```python
"""One-time ingestion of openaccountants .md skills into GraphRAG."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Regex to extract IRC citations like "IRC 1402(a)(12)" or "§199A(b)(2)"
IRC_PATTERN = re.compile(
    r'(?:IRC|§)\s*(\d+[A-Za-z]?(?:\([a-z0-9]+\))*)',
    re.IGNORECASE,
)

SKILL_BASE = Path('.claude/skills/openaccountants')

# Map directories to jurisdiction/topic metadata
DIR_META: dict[str, dict[str, str]] = {
    'federal': {'jurisdiction': 'US_FEDERAL', 'topic': 'FEDERAL'},
    'cross-border': {'jurisdiction': 'INTERNATIONAL', 'topic': 'CROSS_BORDER'},
    'foundation': {'jurisdiction': 'US_FEDERAL', 'topic': 'WORKFLOW'},
}


def _state_meta(state_code: str) -> dict[str, str]:
    return {'jurisdiction': f'STATE_{state_code.upper()}', 'topic': 'STATE_TAX'}


def chunk_markdown(filepath: Path) -> list[dict[str, Any]]:
    """Split a markdown file by ## headings. Keep tables intact within their section."""
    text = filepath.read_text(encoding='utf-8')
    # Extract YAML frontmatter metadata
    name = ''
    version = ''
    if text.startswith('---'):
        end = text.find('---', 3)
        if end != -1:
            frontmatter = text[3:end]
            for line in frontmatter.splitlines():
                if line.startswith('name:'):
                    name = line.split(':', 1)[1].strip()
                elif line.startswith('version:'):
                    version = line.split(':', 1)[1].strip()

    sections: list[dict[str, Any]] = []
    current_heading = filepath.stem  # fallback heading = filename
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith('## ') and current_lines:
            # Flush previous section
            body = '\n'.join(current_lines).strip()
            if body and len(body) > 50:  # skip tiny fragments
                irc_refs = IRC_PATTERN.findall(body)
                sections.append({
                    'heading': current_heading,
                    'body': body,
                    'irc_refs': list(set(irc_refs)),
                    'source_file': str(filepath.relative_to(SKILL_BASE)),
                    'skill_name': name,
                    'skill_version': version,
                })
            current_heading = line.lstrip('#').strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Flush last section
    if current_lines:
        body = '\n'.join(current_lines).strip()
        if body and len(body) > 50:
            irc_refs = IRC_PATTERN.findall(body)
            sections.append({
                'heading': current_heading,
                'body': body,
                'irc_refs': list(set(irc_refs)),
                'source_file': str(filepath.relative_to(SKILL_BASE)),
                'skill_name': name,
                'skill_version': version,
            })

    return sections
```

- [ ] **Step 2: Run chunker on a sample file to verify**

```bash
python -c "
from scripts.ingest_openaccountants import chunk_markdown, SKILL_BASE
from pathlib import Path
chunks = chunk_markdown(SKILL_BASE / 'federal' / 'us-qbi-deduction.md')
print(f'Chunks: {len(chunks)}')
for c in chunks[:3]:
    print(f'  - {c[\"heading\"]} ({len(c[\"body\"])} chars, {len(c[\"irc_refs\"])} IRC refs)')
"
```

Expected: Multiple chunks, each with heading, body, and extracted IRC references.

- [ ] **Step 3: Commit chunker**

```bash
git add scripts/ingest_openaccountants.py
git commit -m "feat(scripts): add openaccountants markdown chunker for GraphRAG ingestion

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 11: Write Ingestion Script — Neo4j + Chroma Writer

**Files:**
- Modify: `scripts/ingest_openaccountants.py`

- [ ] **Step 1: Add the ingestion functions**

```python
import hashlib
import logging

logger = logging.getLogger('taxglobal.ingest_oa')


def _chunk_id(chunk: dict[str, Any]) -> str:
    """Deterministic ID for idempotent upsert."""
    key = f"oa:{chunk['source_file']}:{chunk['heading']}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def ingest_to_chroma(chunks: list[dict[str, Any]], meta: dict[str, str]) -> int:
    """Embed and upsert chunks into Chroma."""
    from backend.knowledge import embedder, vector_store

    embedder.init_embedder()
    vector_store.init_chroma()
    collection = vector_store._collection
    if collection is None:
        logger.warning('Chroma not available, skipping vector ingestion')
        return 0

    count = 0
    for chunk in chunks:
        chunk_id = _chunk_id(chunk)
        embedding = embedder.embed_text(chunk['body'])
        if embedding is None:
            continue
        metadata = {
            'source': 'openaccountants',
            'heading': chunk['heading'],
            'source_file': chunk['source_file'],
            'skill_name': chunk.get('skill_name', ''),
            **meta,
        }
        collection.upsert(
            ids=[chunk_id],
            embeddings=[embedding],
            documents=[chunk['body']],
            metadatas=[metadata],
        )
        count += 1
    return count


def ingest_to_neo4j(chunks: list[dict[str, Any]], meta: dict[str, str]) -> int:
    """Create TaxRule nodes and Source/Jurisdiction edges in Neo4j."""
    from backend.knowledge import neo4j_client

    driver = neo4j_client.get_driver()
    if driver is None:
        logger.warning('Neo4j not available, skipping graph ingestion')
        return 0

    count = 0
    with driver.session() as session:
        for chunk in chunks:
            chunk_id = _chunk_id(chunk)
            jurisdiction = meta.get('jurisdiction', 'US_FEDERAL')

            # Create TaxRule node
            session.run(
                """
                MERGE (r:TaxRule {id: $id})
                SET r.heading = $heading,
                    r.body = $body,
                    r.source = 'openaccountants',
                    r.source_file = $source_file,
                    r.skill_name = $skill_name,
                    r.skill_version = $skill_version
                MERGE (j:Jurisdiction {code: $jurisdiction})
                MERGE (r)-[:APPLIES_TO]->(j)
                """,
                id=chunk_id,
                heading=chunk['heading'],
                body=chunk['body'][:5000],  # truncate for graph storage
                source_file=chunk['source_file'],
                skill_name=chunk.get('skill_name', ''),
                skill_version=chunk.get('skill_version', ''),
                jurisdiction=jurisdiction,
            )

            # Create Source edges for IRC citations
            for irc_ref in chunk.get('irc_refs', []):
                session.run(
                    """
                    MERGE (s:Source {citation: $citation})
                    SET s.type = 'IRC'
                    MERGE (r:TaxRule {id: $rule_id})
                    MERGE (r)-[:REFERENCES]->(s)
                    """,
                    citation=f'IRC {irc_ref}',
                    rule_id=chunk_id,
                )

            count += 1
    return count
```

- [ ] **Step 2: Add the main orchestrator**

```python
def ingest_all() -> dict[str, int]:
    """Walk all OA skill directories and ingest into Neo4j + Chroma."""
    stats = {'chroma': 0, 'neo4j': 0, 'files': 0, 'chunks': 0}

    # Federal skills
    federal_dir = SKILL_BASE / 'federal'
    if federal_dir.exists():
        for md_file in sorted(federal_dir.glob('*.md')):
            if md_file.name == 'README.md':
                continue
            chunks = chunk_markdown(md_file)
            meta = DIR_META['federal']
            stats['chroma'] += ingest_to_chroma(chunks, meta)
            stats['neo4j'] += ingest_to_neo4j(chunks, meta)
            stats['files'] += 1
            stats['chunks'] += len(chunks)
            logger.info('Ingested %s: %d chunks', md_file.name, len(chunks))

    # State skills
    states_dir = SKILL_BASE / 'us-states'
    if states_dir.exists():
        for state_dir in sorted(states_dir.iterdir()):
            if not state_dir.is_dir():
                continue
            state_code = state_dir.name.upper()
            meta = _state_meta(state_code)
            for md_file in sorted(state_dir.glob('*.md')):
                if md_file.name == 'README.md':
                    continue
                chunks = chunk_markdown(md_file)
                stats['chroma'] += ingest_to_chroma(chunks, meta)
                stats['neo4j'] += ingest_to_neo4j(chunks, meta)
                stats['files'] += 1
                stats['chunks'] += len(chunks)
                logger.info('Ingested %s/%s: %d chunks', state_code, md_file.name, len(chunks))

    # Cross-border skills
    xborder_dir = SKILL_BASE / 'cross-border'
    if xborder_dir.exists():
        for md_file in sorted(xborder_dir.glob('*.md')):
            if md_file.name == 'README.md':
                continue
            chunks = chunk_markdown(md_file)
            meta = DIR_META['cross-border']
            stats['chroma'] += ingest_to_chroma(chunks, meta)
            stats['neo4j'] += ingest_to_neo4j(chunks, meta)
            stats['files'] += 1
            stats['chunks'] += len(chunks)
            logger.info('Ingested %s: %d chunks', md_file.name, len(chunks))

    # Foundation skills
    foundation_dir = SKILL_BASE / 'foundation'
    if foundation_dir.exists():
        for md_file in sorted(foundation_dir.glob('*.md')):
            if md_file.name == 'README.md':
                continue
            chunks = chunk_markdown(md_file)
            meta = DIR_META['foundation']
            stats['chroma'] += ingest_to_chroma(chunks, meta)
            stats['neo4j'] += ingest_to_neo4j(chunks, meta)
            stats['files'] += 1
            stats['chunks'] += len(chunks)
            logger.info('Ingested %s: %d chunks', md_file.name, len(chunks))

    return stats


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(name)s %(message)s')
    result = ingest_all()
    print(f"Ingestion complete: {result['files']} files, {result['chunks']} chunks")
    print(f"  Chroma: {result['chroma']} vectors")
    print(f"  Neo4j:  {result['neo4j']} nodes")
```

- [ ] **Step 3: Test chunker on full dataset (dry run)**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from scripts.ingest_openaccountants import chunk_markdown, SKILL_BASE
from pathlib import Path
total_files = 0
total_chunks = 0
for md in sorted(SKILL_BASE.rglob('*.md')):
    if md.name == 'README.md':
        continue
    chunks = chunk_markdown(md)
    total_files += 1
    total_chunks += len(chunks)
print(f'Total: {total_files} files, {total_chunks} chunks')
"
```

Expected: ~200 files, ~500-800 chunks.

- [ ] **Step 4: Run full ingestion (requires Neo4j + Chroma running)**

```bash
PYTHONPATH=. python scripts/ingest_openaccountants.py
```

Expected output: "Ingestion complete: ~200 files, ~600 chunks, Chroma: ~600 vectors, Neo4j: ~600 nodes"

- [ ] **Step 5: Verify search works**

```bash
PYTHONPATH=. python -c "
from backend.knowledge.search import hybrid_search
results = hybrid_search('California Mental Health Services Tax', top_k=3)
for r in results:
    print(f'{r.get(\"score\", 0):.3f} | {r.get(\"heading\", \"\")} | source={r.get(\"source\", \"\")}')"
```

Expected: At least one result from openaccountants with relevant CA MHST content.

- [ ] **Step 6: Commit ingestion script**

```bash
git add scripts/ingest_openaccountants.py
git commit -m "feat(scripts): add GraphRAQ ingestion for openaccountants knowledge base

215 .md files → chunked by ## heading → Neo4j nodes + Chroma vectors.
Incremental (upsert), idempotent, source-tagged as 'openaccountants'.
IRC citations auto-extracted as Source nodes in Neo4j.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Phase 3: Documentation Updates

---

### Task 12: Update Roadmap and Handoff Docs

**Files:**
- Modify: `docs/roadmap_skills_status.md`
- Modify: `docs/handoff_context.md`

- [ ] **Step 1: Update roadmap_skills_status.md**

Add reference source annotations to the Skills table:

```markdown
| 4 | `track_crypto` | `crypto_gain_estimate` + `_crypto_state_tax` | ✅ 已完成 | **增强参考**: tax-prep-beancount (FIFO lot matching, Form 8949 Box A-F, wash sale) |
| 7 | `classify_transaction` | 交易分类(加密/电商品类),待 KB/规则 | 🔲 待 M2 | **参考**: tax-organizer + openaccountants/us-sole-prop-bookkeeping |
| 9 | `extract_w2` | DeepSeek V4 Vision W-2 识别(多模态) | 🔲 待 M3.6 | **参考**: tax-organizer (field mapping) + us-federal-tax-assistant (form line numbers) |
| 10 | `generate_form` | 表单生成(1040 等) | 🔲 待 M2/M3 | **参考**: us-federal-tax-assistant (4-phase: collect→identify→fill→audit) |
| 11 | `check_treaty` | 税收协定/FTC(关联 REQ-004 海外被动收入) | 🔲 待 M2+ | **参考**: openaccountants/cross-border (31 files: withholding-tax, FATCA/CRS, residency) |
```

- [ ] **Step 2: Update handoff_context.md**

Add a new section §2.1 or update §2:

```markdown
### Claude Code Skills（开发工具，不进产品代码）
- **税务专业 skills**（6 个）：us-federal-tax-assistant、tax-organizer、openaccountants（215 文件，51 州全覆盖）、tax-prep-beancount、finance-compliance、finance-wealth-mgmt
- **用途**：写 Codex prompt 时的参考源、PR review 交叉校验、GraphRAQ 知识库数据源
- **Engine Audit**：2026-06-09 完成全量引擎审计，报告见 `docs/engine_audit_report.md`
- **GraphRAQ**：openaccountants 215 .md 已灌入 Neo4j + Chroma（source="openaccountants"）
```

- [ ] **Step 3: Commit docs**

```bash
git add docs/roadmap_skills_status.md docs/handoff_context.md
git commit -m "docs: update roadmap + handoff with skill integration results

- Annotate Skills #4/#7/#9/#10/#11 with reference sources
- Add engine audit + GraphRAG ingestion status to handoff

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Verification Checklist

After all tasks complete, verify:

- [ ] `docs/engine_audit_report.md` exists with summary + all findings
- [ ] All 🔴 (missing) items have been addressed (data JSON updated or backlog item created)
- [ ] All ⚠️ (discrepancy) items have Shaw's decision recorded
- [ ] `scripts/ingest_openaccountants.py` runs successfully
- [ ] `/api/knowledge/search` returns openaccountants content for sample queries
- [ ] `docs/roadmap_skills_status.md` updated with reference annotations
- [ ] `docs/handoff_context.md` updated with skill integration status
- [ ] All existing tests still pass: `python -m unittest discover -s tests`
- [ ] Lint clean: `python -m ruff check engine backend tests`
