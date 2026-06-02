# Step 2.2 - Crypto Gain Engine

## Purpose

Implement `crypto_gain_estimate` using official-source-backed federal ordinary income, long-term capital gains, and NIIT rule data. This unlocks real crypto tax estimates without using prototype multipliers or hard-coded capital gains rates.

## What Changed

- Added `load_capital_gains_rules` to the rule loader.
- Exported `crypto_gain_estimate` from the engine package.
- Added deterministic crypto lot matching for FIFO, LIFO, and HIFO.
- Added input validation with `invalid_input` responses for bad methods, invalid quantities, malformed dates, and oversold assets.
- Added Schedule D style short/long netting.
- Added short-term ordinary tax, long-term capital gains stacking, and NIIT estimates.
- Added golden fixtures and focused engine boundary tests.

## Acceptance Criteria

- FIFO/HIFO/LIFO lot matching golden cases produce the expected short-term and long-term gains.
- The single-filer FIFO tax example at `$100,000` other taxable income produces total tax of `$5,633.00`.
- Invalid inputs return `status: invalid_input` with a clear reason instead of raising to callers.
- Net loss cases return zero tax estimate and explain the `$3,000` deduction/carryforward limitation.
- The engine reads tax rates only from stored JSON rule files.
- Unit tests, golden tests, ruff, data validation, diff check, and prototype hash check pass.

## Files Changed

- `engine/rules_loader.py`
- `engine/__init__.py`
- `engine/tax_engine.py`
- `tests/test_engine.py`
- `tests/test_golden.py`
- `tests/golden/crypto_gain_estimate.json`
- `docs/step2_2_design_crypto.md`
- `docs/step2_2_crypto_engine.md`

## Known Limits

- Wash sale adjustments are not modeled.
- Specific-ID documentation beyond FIFO/LIFO/HIFO is not modeled.
- The `$3,000` capital loss deduction and carryforward are disclosed but not calculated.
- Form 8949 PDF generation is out of scope.
- Staking, airdrops, forks, lending, and other income events are out of scope.
- RSU tax estimates are deferred to Step 2.3.
