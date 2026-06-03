# Step 2.9 交付记录 — REQ-009 Block 3 FEIE 合并计税

日期:2026-06-03
分支:`feature/step2_9-combined-feie`
范围:在 Step 2.7/2.8 的 `income_tax_summary` 基础上合并海外赚取收入 FEIE 税率叠加;不改前端、不改数据。

## 目标
把海外赚取收入并入总税合并器:

- 复用 `feie_estimate()` 计算 physical presence test 和 FEIE exclusion。
- 合格海外收入只把未豁免部分放入 AGI,但联邦普通所得税用 Form 2555 税率叠加: `bracket(ordinary + exclusion) - bracket(exclusion)`。
- NIIT 默认 MAGI 使用 `adjusted_gross_income + feie_excluded_income`,让 FEIE exclusion 按 §1411 加回。
- 海外赚取收入不进入 QBI,不作为 W-2 FICA 或 SE tax 基数。
- `foreign_earned_income=0` 时逐分复现 Block 2。

## 改动文件
- `engine/tax_engine.py`: `income_tax_summary` 新增 `foreign_earned_income`、`days_abroad`;接入 `feie_estimate`;新增 `foreign_earned_income`、`feie_excluded_income`、`foreign_tax_rate_stacking_applied` result 字段。
- `backend/schemas.py`: `IncomeSummaryRequest` 新增 FEIE 字段。
- `tests/golden/income_tax_summary.json`:新增 FEIE Ex1/Ex2/Ex3/Ex4 黄金值。
- `tests/test_engine.py`:覆盖 330 天合格、329 天不合格、低于上限全额豁免、NIIT 加回触发、modified_agi 覆盖、QBI/LTCG/FEIE 组合守卫、foreign=0 回归。
- `tests/test_api_calc.py`:覆盖 `/calc/income-summary` FEIE API 输出。
- `docs/feature_status.md` / `docs/product_backlog.md`:记录 REQ-009 Block 3 进展。

## 黄金值
- Ex1: foreign 200000 / 330 days / single -> exclusion 130000, AGI 70000, ordinary 55000, federal 13200.00, total 13200.00。
- Ex2: foreign 200000 + W-2 50000 + LT gain 30000 -> federal 28216.00, LTCG 4500.00, NIIT 1140.00, payroll 3825.00, total 37681.00。
- Ex3: foreign=0 + W-2 200000 + LT gain 50000 -> total 60465.20,逐分复现 Block 2。
- Ex4: SE 60000 + LT gain 40000 + foreign 100000 -> QBI 8152.23, federal 7759.14, LTCG 3638.84, payroll 8477.73, total 19875.71。

## 已知限制
- 州级 FEIE 不一致未建模;州税仍使用当前 stored state tax_base 路径。
- FEIE 与大额长期资本利得同时存在时,IRS combined Foreign Earned Income/QDCGT worksheet 可能有差异;本步按 MVP stacking simplification 标注。
- 海外自雇、totalization agreements、housing exclusion、bona fide residence test、FTC 和海外被动收入仍未建模。
- 引擎三块已齐,但网页总览/档案同步仍需后续 REQ-002 前端步骤接入 `income_tax_summary` 才能在产品 UI 里完整验证。
