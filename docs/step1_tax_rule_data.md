# Step 1 Tax Rule Data

Date: 2026-06-02

## Purpose

Create the first U.S. 2025 tax-rule data layer from archived official sources rather than prototype hardcoded values.

This step serves the future calculation engine, alert engine, and Copilot retrieval layer. It does not change the UI or implement tax functions yet.

## Completed Work

- Archived official IRS, state tax agency, and sales-tax nexus sources under `data/sources/us/2025/raw/`.
- Added `data/sources/us/2025/source_manifest.json` with source IDs, URLs, local paths, hashes, topics, and status.
- Added machine-readable 2025 rule files:
  - `data/tax_years/2025/us_federal.json`
  - `data/tax_years/2025/us_fica.json`
  - `data/tax_years/2025/us_feie.json`
  - `data/tax_years/2025/us_states.json`
  - `data/tax_years/2025/us_nexus.json`
- Added initial knowledge items prepared for future database ingestion:
  - `data/knowledge/us/2025/us_core_knowledge.json`
- Added validation script:
  - `tests/validate_step1_data.ps1`
- Hardened rule metadata before engine work:
  - effective rules now include `effective_date`
  - top-level rule files use `source_ids`
  - validation checks rule-file source references, not only knowledge references
  - validation blocks pending state rules from carrying usable rates or brackets

## Acceptance Criteria

- Every effective rule references archived official sources.
- Manifest entries point to real local files.
- Manifest hashes match the archived files.
- JSON files parse successfully.
- Core federal/FICA/FEIE fields match the verified official-source values.
- Knowledge items reference known source IDs.
- Effective rules and knowledge items include `effective_date`.
- Rule files do not use the deprecated `sources` key.
- `source_pending` / `pending_extraction` state rules cannot carry usable rates or brackets.
- Prototype files remain untouched.

## Validation Commands

```powershell
powershell -ExecutionPolicy Bypass -File tests/validate_step1_data.ps1
Get-FileHash -Algorithm SHA256 -LiteralPath index.html, frontend\index.html
git diff --check
```

## Known Limits

- California and New York income-tax schedule sources are archived, but bracket extraction is marked `pending_extraction` until a reliable PDF/HTML table extraction path is added.
- Massachusetts official tax-rate page returned 403 during scripted archive, so Massachusetts remains `source_pending`.
- Texas individual income tax is not yet archived from an official source, so Texas state income tax remains `source_pending` despite prototype assumptions.
- SSA 2025 COLA page returned 403 during scripted archive; FICA uses archived IRS sources for the first data pass.
- Illinois official HTML snapshot redacts an embedded Mapbox public token to satisfy GitHub push protection; the manifest records this source as `archived_redacted`.
- This step does not implement calculation functions or API routes.

## Claude Review Focus

- Whether the source manifest is enough for future database ingestion.
- Whether effective rules are appropriately sourced.
- Whether pending/unverified state rules are clearly blocked from calculation.
- Whether validation catches missing source files, hash drift, and bad JSON.
- Whether validation now catches rule-file source reference drift and unsafe pending-state rates.
