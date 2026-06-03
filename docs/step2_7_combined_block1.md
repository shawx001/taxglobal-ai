# Step 2.7 交付记录 — REQ-009 Block 1 赚取收入合并计税

日期:2026-06-03
分支:`feature/step2_7-combined-earned-income`
范围:扩 `income_tax_summary`,合并 W-2 工资、自雇净利和其它普通收入;不改前端、不改税率数据。

## 目标
把原本偏自雇场景的 `income_tax_summary` 扩成 REQ-009 的第一块总税合并器:

- W-2 工资进入 AGI、累进所得税和员工侧 FICA。
- 自雇净利继续计算 SE tax、1/2 SE above-line deduction 和 QBI。
- W-2 与自雇共享 Social Security wage base。
- Additional Medicare tax 用 W-2 + SE net earnings 的合并阈值。
- `w2_wages=0` 时逐分复现旧的 self-employment-only 结果。

## 改动文件
- `engine/tax_engine.py`:新增 `_combined_payroll` helper;扩 `income_tax_summary` 的 `w2_wages` 入参、result/breakdown/input 字段和 assumptions。
- `backend/schemas.py`: `IncomeSummaryRequest` 新增 `w2_wages: float = Field(default=0, ge=0)`。
- `tests/golden/income_tax_summary.json`:新增 W-2 + 自雇两个黄金用例和 `w2_wages=0` 回归用例。
- `tests/test_engine.py`:覆盖 W-2 占满 SS 基数、Additional Medicare 合并触发、QBI 高收入淘汰、w2=0 回归。
- `tests/test_api_calc.py`:覆盖 `/calc/income-summary` 的 W-2 + 自雇 API 输出。
- `docs/feature_status.md` / `docs/product_backlog.md`:记录 REQ-009 Block 1 进展。

## 黄金值
- Ex A: W-2 150000 + 自雇 50000, single -> total_tax 50458.23, payroll 16050.48, QBI 9542.45。
- Ex B: W-2 250000 + 自雇 60000, single -> total_tax 89614.82, SE SS base 被 W-2 占满后为 0, Additional Medicare 948.69, QBI 0.00。
- Ex C: 自雇 100000, W-2 缺省 0 -> total_tax 22760.15, 与旧 income_tax_summary 逐分一致。

## 已知限制
- 本步只合并赚取收入。资本利得长期/短期叠加、NIIT 总 MAGI、FEIE 税率叠加和 FTC 仍在后续 REQ-009 blocks。
- W-2 工资假设已包含 W-2 报告的 RSU 归属值;期权、AMT、海外被动收入、抵免未建模。
- `other_ordinary_income` 只作为普通所得税叠加收入,不作为 W-2 或 SE payroll tax 基数。
- 州税残余限制沿用 Step 2.5 assumptions:NY recapture、CA Schedule CA、IL/GA 退休减项、州抵免等仍未建模。
