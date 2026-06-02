# Step 5 - Frontend Income Tax API

## Purpose

Connect the `frontend/index.html` personal income tax module to the FastAPI backend while keeping the root `index.html` frozen as the prototype reference.

## What Changed

- Added development CORS support to the FastAPI app for local static frontend usage.
- Added a CORS regression test.
- Added `frontend/api.js` as the frontend API wrapper for `/calc/*` calls.
- Updated the personal income tax path in `frontend/index.html` to call:
  - `POST /calc/federal-income`
  - `POST /calc/fica`
  - `POST /calc/state-income`
- Stopped the personal income tax module from falling back to old frontend tax calculations.
- Added explicit frontend handling for `not_covered`, validation/API errors, and backend service outages.
- Kept the root `index.html` unchanged.

## Acceptance Criteria

- Backend tests pass, including CORS headers for local frontend origins.
- Root `index.html` SHA256 remains `833508998A7FF1C783646E5E8B35E8C66AB27AE5FF88193318C2A1F2007B4B69`.
- `frontend/index.html` successfully displays backend-powered federal, FICA, and state income tax results.
- CA/NY-style unavailable state rules show an honest unavailable-state message instead of fake state tax.
- Backend outage shows an unavailable-service message and does not fall back to stale frontend results.

## Browser Verification

- Served `frontend/` locally at `http://127.0.0.1:5173`.
- Started FastAPI at `http://127.0.0.1:8000`.
- Verified the personal income tax module calls `/calc/federal-income`, `/calc/fica`, and `/calc/state-income`.
- Verified FL shows backend federal/FICA/state results with citations.
- Verified CA shows `not_covered` with the pending extraction reason instead of a fake state-tax number.
- Stopped FastAPI and verified the frontend shows the backend-unavailable message instead of falling back to old frontend calculations.

## Files Changed

- `backend/main.py`
- `tests/test_api_calc.py`
- `frontend/api.js`
- `frontend/index.html`
- `docs/feature_status.md`
- `docs/step5_design_frontend.md`
- `docs/step5_frontend_api.md`

## Known Limits

- Only the personal income tax module is connected to the backend in this step.
- Other modules still keep prototype behavior until their own frontend integration steps.
- No frontend JavaScript automation framework is added yet.
- CORS is development-only and must be tightened for production.
- No profile income-bucket redesign in this step.
