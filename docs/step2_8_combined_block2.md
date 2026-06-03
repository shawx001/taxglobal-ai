# Step 2.8 交付记录 — REQ-009 Block 2 资本利得合并计税

日期:2026-06-03
分支:`feature/step2_8-combined-capital-gains`
范围:在 Step 2.7 的 `income_tax_summary` 基础上合并短期/长期资本利得与 NIIT;不改前端、不改数据。

## 目标
把资本利得并入总税合并器:

- 短期资本利得进入 AGI 和普通所得税档,但不计 W-2 FICA、SE tax 或 QBI。
- 长期资本利得进入 AGI 和总应税收入,但用 QDCGT stacking 按 0%/15%/20% 档单独计税。
- NIIT 3.8% 使用 `us_capital_gains.json` 的阈值和费率,按 `min(net investment income, MAGI over threshold)` 计算。
- `long_term_capital_gain=0` 且 `short_term_capital_gain=0` 时逐分复现 Block 1。

## 改动文件
- `engine/tax_engine.py`: `income_tax_summary` 新增 `long_term_capital_gain`、`short_term_capital_gain`、`modified_agi`;加载一次 `us_capital_gains.json`;新增 `ordinary_taxable_income`、`long_term_capital_gains_tax`、`net_investment_income_tax` 等 result 字段。
- `backend/schemas.py`: `IncomeSummaryRequest` 新增资本利得和 `modified_agi` 字段。
- `tests/golden/income_tax_summary.json`:新增资本利得 Ex1/Ex2 和 gains=0 回归。
- `tests/test_engine.py`:覆盖短期利得普通档、NIIT 全额/截顶、长期 0% 档、gains=0 回归。
- `tests/test_api_calc.py`:覆盖 `/calc/income-summary` 资本利得 API 输出。
- `docs/feature_status.md` / `docs/product_backlog.md`:记录 REQ-009 Block 2 进展。

## 黄金值
- Ex1: W-2 200000 + 长期利得 50000, single -> ordinary_taxable_income 185000, federal 37247.00, LTCG 7500.00, NIIT 1900.00, total_tax 60465.20。
- Ex2: W-2 150000 + 自雇 50000 + 长期利得 40000, single -> QBI 4692.55, ordinary_taxable_income 178019.71, federal 35571.73, LTCG 6000.00, NIIT 1433.07, total_tax 59055.28。
- Ex3: W-2 150000 + 自雇 50000 + gains=0 -> federal 34407.75, LTCG 0.00, NIIT 0.00, total_tax 50458.23。

## 已知限制
- 本步没有建模净资本亏损的 $3,000 抵扣或结转;负利得按 0 截断。
- `modified_agi` 未传时,NIIT 使用 `adjusted_gross_income` 作为 MVP 近似;完整申报场景应传入 return-level MAGI。
- WA 长期资本利得 excise 不在 `income_tax_summary` 中计算;仍走独立 crypto 模块的 WA state path。
- FEIE 税率叠加、FTC、AMT、期权、海外被动收入和前端总览仍在后续 REQ-009 blocks。
