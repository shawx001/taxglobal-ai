# Data Layout

This directory separates official source material, knowledge-base content, and calculation rule data.

## `sources/`

Archived official documents and page snapshots.

Use this for IRS, SSA, state tax agency, Treasury, FinCEN, and official marketplace tax-policy materials.

Example:

```text
data/sources/us/2025/raw/
data/sources/us/2025/source_manifest.json
```

Rules:

- Store source documents or page snapshots before extracting rules.
- Treat prototype values as unverified leads, not official facts.
- Every source entry must include a URL, retrieval timestamp, local path, hash, publisher, tax year, jurisdiction, topics, and status.
- Do not delete old source files when a newer source supersedes them.

## `knowledge/`

Structured knowledge items prepared for future database ingestion and retrieval.

Use this for human-readable tax explanations, alert triggers, planning guidance, and citations extracted from archived sources.

Example:

```text
data/knowledge/us/2025/
```

Rules:

- Every knowledge item must trace back to one or more archived source entries.
- Knowledge items are not calculation rules by themselves.
- If a topic is not covered by the knowledge base, the product must say it is not covered rather than inventing an answer.

## `tax_years/`

Versioned calculation rule data used by the tax engine.

Example:

```text
data/tax_years/2025/us_federal.json
data/tax_years/2025/us_fica.json
data/tax_years/2025/us_states.json
data/tax_years/2025/us_feie.json
```

Rules:

- Store machine-readable values used by the calculation engine.
- Do not put UI copy or long explanations here.
- Each rule must reference archived sources and include citations.
