# Step 3 - Golden Tests, Lint, and CI

## Purpose

Lock the JSON-backed tax engine behind repeatable golden fixtures before adding more tax domains. This step makes the current engine outputs reviewable, reproducible, and suitable for CI.

## What Changed

- Added a unified golden test runner that loads `tests/golden/*.json` and dispatches each fixture to the matching engine function.
- Added golden fixtures for federal income tax, FICA, FEIE, and state income tax.
- Extended the self-employment golden fixture with negative-profit and MFJ threshold cases.
- Moved duplicated SE and nexus fixture loops out of `tests/test_engine.py`; kept focused unit and boundary probes there.
- Added `ruff.toml` for Python linting.
- Added GitHub Actions CI with lint, unit/golden tests, non-blocking dependency audit, and data validation.

## Acceptance Criteria

- `python -m unittest discover -s tests -v` passes.
- `ruff check engine tests` passes.
- `powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1` passes.
- `git diff --check` passes.
- Root `index.html` and `frontend/index.html` SHA-256 hashes remain identical.

## Files Changed

- `.github/workflows/ci.yml`
- `ruff.toml`
- `docs/step3_golden_tests.md`
- `engine/rules_loader.py`
- `engine/tax_engine.py`
- `tests/test_engine.py`
- `tests/test_golden.py`
- `tests/golden/federal_income_tax.json`
- `tests/golden/fica_tax.json`
- `tests/golden/feie_estimate.json`
- `tests/golden/state_income_tax.json`
- `tests/golden/self_employment_tax.json`

## Known Limits

- RSU and crypto golden tests are deferred until official 2025 capital gains and NIIT rule data are archived in `data/`.
- CI includes `pip-audit || true` because the project does not yet have a dependency manifest.
