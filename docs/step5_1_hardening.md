# Step 5.1 - Frontend/API Hardening

## Purpose

Address Step 5 review findings without expanding product scope or changing tax calculation logic.

## What Changed

- Added `escapeHtml(value)` in `frontend/index.html`.
- Escaped backend-provided strings before inserting them into `innerHTML` or HTML attributes:
  - citation text and source IDs
  - breakdown labels
  - assumptions
  - `not_covered` reasons
- Updated `frontend/api.js` so HTTP 2xx responses with missing/invalid JSON payloads raise `invalid_response`.
- Tightened development CORS:
  - default origins are localhost / 127.0.0.1 only
  - `null` origin removed
  - `allow_headers` narrowed to `Content-Type`
  - `TAXGLOBAL_CORS_ORIGINS` can override allowed origins
- Added a negative CORS test for an untrusted origin.
- Recorded REQ-003 in `docs/product_backlog.md` for deleting legacy frontend `caStateTax` / `nyStateTax` when remaining modules migrate to backend state tax.
- Kept the foreign-income / FEIE tax tab visible for all profiles instead of only digital nomad profiles.
- Rebuilt tax subtabs when profile identity selections change so the tax module stays synchronized with profile changes.
- Recorded REQ-004 in `docs/product_backlog.md` for separating foreign earned income / FEIE from foreign passive income / FTC.

## Acceptance Criteria

- Frontend no longer inserts backend-provided strings into HTML without escaping.
- Network errors still surface as `service_unavailable`.
- Non-2xx backend responses still surface as `request_failed`.
- HTTP 2xx invalid response payloads surface as `invalid_response`.
- Local frontend origin `http://127.0.0.1:5173` still receives CORS allow-origin.
- Untrusted origin `http://evil.example` does not receive CORS allow-origin.
- Root `index.html` remains frozen.

## Verification

- `python -m unittest discover -s tests -v` -> 39 tests passed.
- `ruff check engine backend tests` -> passed.
- `pip-audit -r backend/requirements.txt` -> no known vulnerabilities.
- `powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1` -> passed.
- `git diff --check` -> passed.
- Root `index.html` SHA256 remains `833508998A7FF1C783646E5E8B35E8C66AB27AE5FF88193318C2A1F2007B4B69`.
- Browser smoke at `http://127.0.0.1:5173/index.html`:
  - CA personal-income result still renders backend state tax and `ca_2025_540_tax_rate_schedules`.
  - Malicious citation/reason/breakdown/assumption strings render as text and create no `img`, `svg`, `script`, or `b` nodes.
  - A 2xx response with null body is mapped to `invalid_response`.
  - Default tech profile shows `海外收入 / FEIE`.
  - Switching the profile to digital nomad rebuilds the tax subtabs and keeps `海外收入 / FEIE` visible.
  - The FEIE panel states that passive foreign income is not FEIE and belongs to future FTC / passive-income handling.

## Files Changed

- `backend/main.py`
- `frontend/api.js`
- `frontend/index.html`
- `tests/test_api_calc.py`
- `docs/product_backlog.md`
- `docs/step5_1_design_hardening.md`
- `docs/step5_1_hardening.md`

## Known Limits

- Legacy `caStateTax` / `nyStateTax` functions are recorded in backlog but not deleted in this step.
- Frontend JavaScript still does not have a dedicated automated unit-test framework.
- Production CORS policy still needs deployment-specific configuration.
