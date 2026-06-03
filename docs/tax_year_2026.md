# Step A 2026 税年数据集交付记录

日期：2026-06-03
分支：`feature/tax-year-2026`

## 目标

新增 2026 税年规则数据，并把引擎/后端 schema 的默认 `tax_year` 从 2025 切到 2026；同时把既有 2025 golden/API/engine 测试显式钉到 `tax_year=2025`，保证旧税年仍逐分回归。

## 改动

- 新增 `data/tax_years/2026/`：
  - `us_federal.json`
  - `us_fica.json`
  - `us_capital_gains.json`
  - `us_qbi.json`
  - `us_feie.json`
  - `us_states.json`
  - `us_nexus.json`
- 新增 2026 source manifest 与 IRS Rev. Proc. 2025-32 归档 PDF。
- `us_states.json` / `us_nexus.json` 复制 2025 参数，并对每个州/阈值标记 `state_parameter_year: 2025`；2026 州参数更新留 Step B。
- `engine/rules_loader.py`、`engine/tax_engine.py`、`backend/schemas.py` 默认 `tax_year=2026`。
- 既有 2025 测试显式传 `tax_year=2025`；新增 2026 默认路径 golden 和单测。

## 官方来源与口径

- IRS Rev. Proc. 2025-32：2026 标准扣除、普通所得税档、长期资本利得档、FEIE、QBI 阈值。
- SSA Contribution and Benefit Base：2026 Social Security wage base = 184,500。
- SSA 页面 raw fetch 被边缘访问控制拦截，因此 manifest 中 `ssa_press_2026` 标为 `source_verified_raw_fetch_blocked`，不伪装成 archived；数据校验允许该状态但要求 notes。

## 重要校正

设计 prompt 写 QBI single/HOH/MFS 全部为 201,775。逐项核 IRS Rev. Proc. 2025-32 后，采用官方表：

- single / head_of_household / qualifying_surviving_spouse：201,750 → 276,750
- married_filing_separately：201,775 → 276,775
- married_filing_jointly：403,500 → 553,500

这是按官方 “All Other Returns” 与 “Married Filing Separately” 分行录入，不按 prompt 的合并写法。

## 2026 锚点

默认不传 `tax_year`：

- `income_tax_summary(w2_wages=200000, filing_status="single")`
  - `federal_income_tax`: 36,734.00
  - `total_payroll_tax`: 14,339.00
  - `total_tax`: 51,073.00

新增 2026 A-D golden：

- A W-2 200k + 长期资本利得 50k：`total_tax` 60,473.00
- B FEIE 200k / 330 天：`feie_excluded_income` 132,900.00，`total_tax` 12,240.00
- C 自雇 60k + 长期 40k + 海外 100k / 330 天：`qbi_deduction` 7,932.23，`total_tax` 19,320.51
- D 自雇 100k + CA：`state_parameter_year` 2025 口径下 CA 州税 4,550.96，`total_tax` 26,915.51

## 已知限制

- 州所得税、WA capital gains excise、Nexus 阈值的 2026 最终州参数本步不更新；数据中已明确标注 `state_parameter_year: 2025`。
- OBBBA 中小费/加班、SALT、老人额外扣除、QBI $400 最低扣除等不在当前引擎范围。
- 2026 SSA source raw archival blocked，但官方值已核实并在 manifest 中诚实标注。

## 验收

- `python -m unittest discover -s tests -v`：84 tests OK
- `ruff check engine backend tests`：通过
- `powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1`：通过
- `git diff --check`：待最终提交前复跑
- 根 `index.html` 与 `frontend/index.html`：本步不改
