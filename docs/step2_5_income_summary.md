# Step 2.5 交付记录 — `income_tax_summary` 自雇总税

日期:2026-06-02
分支:`feature/step2_5-income-summary`

## 目标

实现纯函数 `income_tax_summary`,把自雇净利润串成完整自雇总税:

- SE 税 + Additional Medicare Tax
- 1/2 SE tax above-line deduction
- 自雇健保/退休 above-line deduction 输入
- 联邦标准扣除或调用方传入 deduction
- QBI deduction
- 联邦 ordinary income tax
- 按 Step 1.4 `tax_base` 计算的精确州税基与州所得税

## 改动

- `engine/tax_engine.py`:新增 `_state_taxable_base` helper 和 `income_tax_summary`。
- `engine/__init__.py`:导出 `income_tax_summary`。
- `tests/golden/income_tax_summary.json`:新增 FL/WA/NV/CA/NY/GA/IL/CO/MA + 低收入 Case 2 黄金用例。
- `tests/test_engine.py`:新增低收入仍欠 SE 税、未知州 not_covered、CO QBI addback、非法 filing status 边界测试。
- `docs/product_backlog.md`:新增/更新 REQ-011 州级税基一致性。
- `docs/feature_status.md`:标记 `income_tax_summary` Step 2.5 已实现。

## 黄金值

`net_self_employment_profit=100000`, `filing_status=single` 的公共部分:

- self_employment_tax: 14129.55
- additional_medicare_tax: 0.00
- deductible_half_se_tax: 7064.78
- adjusted_gross_income: 92935.22
- deduction_used: 15000.00
- taxable_before_qbi: 77935.22
- qbi_deduction: 15587.04
- taxable_income: 62348.18
- federal_income_tax: 8630.60

州税结果:

- FL/WA/NV: state tax 0.00,total 22760.15
- CA: state_base 87229.22,state tax 4550.96,total 27311.11
- NY: state_base 84935.22,state tax 4527.86,total 27288.01
- GA: state_base 80935.22,state tax 4200.54,total 26960.69
- IL: state_base 90085.22,state tax 4459.22,total 27219.37
- CO: state_base 77935.22,state tax 3429.15,total 26189.30
- MA: state not_covered,total 22760.15(仅联邦+SE)

低收入 Case 2 (`net_self_employment_profit=10000`, single, FL):

- self_employment_tax 1412.96
- federal_income_tax 0.00
- taxable_income 0.00
- total_tax 1412.96
- quarterly_estimate 353.24

## 已知限制

- 本步聚焦自雇总税;W-2/RSU/海外剩余/加密合并到同一个总税函数仍属后续 REQ-009 扩展。
- 州税基已按 `tax_base` 建模核心起点、州标准扣除/免税额、QBI 一致性;残余州级调整未建模,包括 NY recapture、IL/GA 退休减项、CA Schedule CA、年龄/盲人额外扣除、州级抵免、IL 受养人数。
- IL exemption allowance 本步按申报身份假设 MFJ=2 个 exemption,其他 filing status=1 个 exemption。
- NIIT 不适用于本步的积极自雇收入 summary。
- not_covered 州总税仅含联邦 + SE,并在 assumptions 标注。
