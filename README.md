# TaxGlobal AI

TaxGlobal AI is an AI-assisted tax planning and compliance platform for globally mobile, multi-income users. The current repository starts from a clickable single-file prototype and will evolve into a U.S.-first MVP with auditable calculations and knowledge-backed recommendations.

## Current Status

- Prototype complete: `index.html`
- Working frontend copy: `frontend/index.html`
- Product docs are kept in the repository root:
  - `TaxGlobal_AI_PRD_v1.1.md`
  - project plan markdown
  - goal-driven development plan markdown
  - MVP checklist markdown

## MVP Boundary

The first build is U.S.-first:

- Federal income tax
- FICA and Additional Medicare Tax
- Selected state income tax
- RSU estimate
- Self-employment tax
- FEIE basic estimate
- Crypto cost-basis estimate
- E-commerce Nexus estimate
- Knowledge-backed alerts and Copilot responses

Deferred for now:

- Model training, LoRA, vLLM
- Full international tax coverage
- Real OAuth integrations
- Real marketplace connectors
- OCR/VLM document extraction
- E-file
- Full enterprise tax module

## Architecture Direction

```text
frontend/  UI only
backend/   FastAPI orchestration and API routes
engine/    Pure tax calculation and rule evaluation
data/      Versioned tax rules, knowledge items, and source metadata
tests/     Golden tests and API tests
docs/      Engineering notes and review artifacts
```

## Source of Truth Rule

Production logic should trust the database/knowledge store, not live web pages.

- External sources are ingestion inputs only.
- The calculation engine reads current effective rules from stored data.
- Copilot retrieves from the knowledge base and calls the engine for amounts.
- Dashboard alerts are triggered by profile data plus knowledge rules.
- Missing coverage should return "knowledge base not covered yet" and create an update task.
- Superseded rules are retained for audit instead of deleted.

## Development Discipline

Every change must be verified. Code changes need automated tests; documentation, structure, and configuration changes need an appropriate check such as file hashes, schema validation, or readability checks. Each step should produce a small reviewable diff with purpose, changed files, validation results, and known limits.

## Prototype Sync Rule

During the migration period, `index.html` and `frontend/index.html` must stay identical. Check them with:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath index.html, frontend\index.html
```

When the new frontend fully takes over, remove the root-level prototype copy and delete this sync rule.

## Local Prototype

Open either file in a browser:

- `index.html`
- `frontend/index.html`

The files are intentionally duplicated for Step 0 so the original prototype remains untouched while the new project structure is introduced.

## Next Step

Step 1: extract U.S. 2025 tax rule data into versioned JSON files under `data/tax_years/2025/`.
