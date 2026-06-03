# Step 5.7 Delivery - Nexus Frontend

Goal: move the e-commerce Nexus monitor from frontend hard-coded thresholds and fake sales-tax estimates to the backend `/calc/nexus` endpoint.

## What Changed

- Added `TaxGlobalApi.nexus(payload)` in `frontend/api.js`.
- Changed `renderNexus()` in `frontend/index.html` to call `/calc/nexus` concurrently for each seller-liable state.
- Converted ecom demo sales from `$K` to dollars before sending `sales_amount` to the engine.
- Rendered each state row from backend fields:
  - `threshold.sales_amount`
  - `status_label`
  - `exceeded`
  - `approaching`
  - citations
- Removed the frontend `STATE_THR` hard-coded threshold table.
- Removed the fake `sales * 0.0725` "estimated tax due" calculation.
- Not-covered or failed state calls now render an honest "nexus rules not covered" row with no fake threshold or percent.
- Dashboard ecom alerts no longer make frontend threshold judgments; they point users to the backend-driven Nexus monitor.
- Updated visible ecom copy to say the monitor provides compliance/registering guidance, not made-up tax amounts.

## Files Changed

- `frontend/api.js`
- `frontend/index.html`
- `docs/product_backlog.md`
- `docs/feature_status.md`
- `docs/step5_7_design_nexus_frontend.md`
- `docs/step5_7_nexus_frontend.md`

## Validation

- Headless `/calc/nexus` checks:
  - CA sales `$600,000` -> `triggered`, threshold `$500,000`
  - CA sales `$450,000` -> `approaching`
  - WA/unknown state -> `not_covered`
- Grep confirmed no remaining frontend `STATE_THR`, `0.0725`, or fake `owed` tax calculation.
- Full local gate for this PR:
  - `python -m unittest discover -s tests -v`
  - `ruff check engine backend tests`
  - `pip-audit -r backend/requirements.txt`
  - `powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1`
  - `git diff --check`
  - root `index.html` SHA256 remains `833508998A7FF1C783646E5E8B35E8C66AB27AE5FF88193318C2A1F2007B4B69`

## Known Limits

- `renderNexus()` does not invent transaction counts when the demo store data lacks them; states with transaction-count requirements rely on the backend's existing no-transaction-count behavior.
- This step only judges registration obligation. Sales tax amount calculation remains out of scope.
- Remaining REQ-003 cleanup waits for the old 6-country comparison and W-2/prototype tax paths to migrate off frontend state-tax helpers.
