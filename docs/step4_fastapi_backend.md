# Step 4 - FastAPI Backend

## Purpose

Expose the completed tax engine as a minimal HTTP API for Step 5 frontend integration. The API layer only validates and orchestrates requests; all tax calculations remain in `engine/`.

## What Changed

- Added a FastAPI app under `backend/`.
- Added Pydantic request schemas for all calculation endpoints.
- Added `/health` plus eight `/calc/*` routes that call the matching engine function.
- Added request-id middleware with `X-Request-ID` response headers and structured logs.
- Added unified error responses for Pydantic validation errors, engine `invalid_input`, and unexpected internal errors.
- Added API tests using Starlette `TestClient`.
- Added pinned backend dependencies.
- Updated CI to install backend dependencies, lint `backend`, and run blocking `pip-audit`.

## Acceptance Criteria

- `/health` returns HTTP 200 and `{"status": "ok"}`.
- All eight `/calc/*` endpoints return engine payloads for valid inputs.
- Engine `not_covered` responses use HTTP 200.
- Engine `invalid_input` responses use HTTP 422 with the unified error body.
- Pydantic validation failures use HTTP 422 with the unified error body.
- Unexpected exceptions use HTTP 500 with the unified error body and no stack leakage.
- Every response has `X-Request-ID`.
- `/openapi.json` contains all calculation routes.

## Files Changed

- `.github/workflows/ci.yml`
- `backend/__init__.py`
- `backend/errors.py`
- `backend/main.py`
- `backend/requirements.txt`
- `backend/routes/__init__.py`
- `backend/routes/calc.py`
- `backend/schemas.py`
- `docs/step4_fastapi_backend.md`
- `tests/test_api_calc.py`

## Known Limits

- No authentication or user accounts.
- No persistence or audit-log database.
- No rate limiting.
- No production CORS policy.
- No combined income summary endpoint.
- No deployment configuration.
