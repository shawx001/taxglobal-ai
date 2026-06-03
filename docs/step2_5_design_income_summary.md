# Step 2.5 设计文档 — `income_tax_summary`(自雇总税,准确无误)

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：Step 2/2.1/2.4 引擎、`tax_rules_self_employment.md`、IRS §1401/§164(f)/§199A/§63
分支：`feature/step2_5-income-summary`
角色：Claude 出设计 + 已手算黄金值;Codex 实现。

> 目标:把零散引擎串成**自雇总税**——SE 税 + ½SE 抵扣 + QBI + 标准扣除 + 联邦累进 + 州税,顺序正确、数值准确。**联邦 + SE 部分做到精确;州税带"估算"标注**(州对 QBI/标准扣除不一致,见 §4 IS-5)。复用现有引擎、Decimal、不裸写税率。

---

## 1. 函数契约
```
income_tax_summary(
    net_self_employment_profit: float = 0.0,
    other_ordinary_income: float = 0.0,     # 预留(W-2 等),本步默认 0
    filing_status: str = "single",
    state_code: str | None = None,
    se_health_insurance: float = 0.0,        # above-line 扣除
    retirement_contributions: float = 0.0,   # SEP/Solo401k,above-line
    qbi_w2_wages: float = 0.0, qbi_ubia: float = 0.0, is_sstb: bool = False,
    deduction: float | None = None,          # None=标准扣除
    tax_year: int = 2025,
) -> dict
```
`result` 含:`self_employment_tax`、`additional_medicare_tax`、`deductible_half_se_tax`、`adjusted_gross_income`、`deduction_used`、`qbi_deduction`、`taxable_income`、`federal_income_tax`、`state_income_tax`(或 not_covered 标记)、`total_tax`、`quarterly_estimate`。

## 2. 计算链(复用引擎,Decimal,组合各引擎的 _money 结果)
```
SE = self_employment_tax(net_self_employment_profit, filing)        # §1401
above_line = SE.deductible_half_se_tax + se_health_insurance + retirement_contributions
agi = max(0, net_self_employment_profit + other_ordinary_income − above_line)
ded = deduction if 提供 else 标准扣除[filing]              # us_federal.standard_deduction
taxable_before_qbi = max(0, agi − ded)
qbi_amount = max(0, agi − other_ordinary_income)            # 经营收入部分(QBI 只算经营)
QBI = qbi_deduction(qbi=qbi_amount, taxable_income=taxable_before_qbi, filing,
                    w2_wages=qbi_w2_wages, ubia=qbi_ubia, is_sstb=is_sstb).deduction
taxable_income = max(0, taxable_before_qbi − QBI)
federal_income_tax = bracket_tax(taxable_income, us_federal.brackets[filing])   # 注意:不用 federal_income_tax(),避免重复减标准扣除
state = state_income_tax(state_code, taxable_income, filing) if state_code else None
total_tax = SE.self_employment_tax + SE.additional_medicare_tax + federal_income_tax + (state.tax if state ok else 0)
quarterly_estimate = total_tax / 4                          # §6654
```
NIIT 不计(积极自雇非投资收益)。

## 3. 黄金用例(已手算;联邦+SE 精确;FL 零州税 → 总数精确)
**Case 1 — net 100000, single, FL:**
| 字段 | 值 |
|---|---|
| self_employment_tax (§1401) | 14129.55 |
| additional_medicare_tax | 0.00 |
| deductible_half_se_tax | 7064.78 |
| adjusted_gross_income | 92935.22 |
| deduction_used (标准) | 15000.00 |
| qbi_deduction | 15587.04 |
| taxable_income | 62348.18 |
| federal_income_tax | 8630.60 |
| state_income_tax (FL) | 0.00 |
| **total_tax** | **22760.15** |
| quarterly_estimate | 5690.04 |

**Case 2 — net 10000, single, FL(低于标准扣除):** SE 税 **1412.96**、federal 0.00、taxable 0、**total 1412.96**、quarterly 353.24。→ 演示"收入低于标准扣除仍欠 SE 税"。

**Case 3 — net 100000, single, CA:** 同 Case 1 到 taxable 62348.18;CA 累进州税 ≈ **2371.90**,**但标注为估算**(见 IS-5)。total(含州)≈ 25132.05。

> 组合"已 _money 的引擎结果"求和,Case 1/2 的总数稳定(我手算逐分核过)。Codex 实现后我会独立重算逐分对齐。

## 4. 设计决策
- **IS-1** 本步聚焦自雇;`other_ordinary_income` 预留默认 0(将来 REQ-009 扩成全收入合并)。
- **IS-2** 复用引擎、组合其 _money 输出求和(确定、不重复推导);Decimal。
- **IS-3** QBI 输入 = 经营收入(agi − other_ordinary_income);QBI 的整体上限用 taxable_before_qbi。
- **IS-4** 联邦税用 `bracket_tax(最终 taxable)`,**不调 `federal_income_tax()`**(它会再减一次标准扣除,会重复)。
- **IS-5(关键诚实点)** 州税 = `state_income_tax(州, 联邦最终 taxable)`,但**很多州不认 QBI、有自己的标准扣除**(如 CA),所以**州税是估算**——assumptions 必须写明"州税未建模州级 QBI 非一致性与州标准扣除,可能偏差;联邦+SE 为精确部分"。零税州(FL/NV/WA)无此问题,总数精确。
- **IS-6** NIIT 不计(N/A 自雇积极收入)。
- **IS-7** 州 not_covered(CA/NY 现在已可算;MA/TX 等)→ 州税标 not_covered,总税仅含联邦+SE,并提示。

## 5. 由此新增 Backlog
```
| REQ-011 | 州级税基一致性(州标准扣除 / 州不认 QBI 等) | 州数据+引擎 | 🟢 | income_tax_summary 目前用联邦最终 taxable income 算州税,属估算;CA 等州不允许 QBI 扣除、有独立标准扣除,州税会偏差。需补各州税基调整规则后精确化。当前必须标注"州税为估算"。 |
```

## 6. 验收
- 独立重算 Case 1/2 逐分对齐(尤其 total 22760.15 / 1412.96);Case 3 验 CA 路径跑通 + 州税标估算。
- 纯函数、Decimal、复用引擎、无裸写税率(grep)、不调 federal_income_tax 重复减扣除。
- ruff + unittest + 数据校验 + pip-audit CI 全绿;根 index.html hash 未变。
- Claude review 通过([Blocker]/[Major]/[Minor]),重点核计算链顺序与 QBI/标准扣除的交互。

## 7. 交付物与分工
- **Codex**:`engine/tax_engine.py` 加 `income_tax_summary`(复用 self_employment_tax/qbi_deduction/bracket_tax/state_income_tax);`__init__` 导出;`tests/golden/income_tax_summary.json`(Case 1/2 + CA 路径);`tests/test_engine.py` 边界;`product_backlog.md` 加 REQ-011;设计 + 交付记录 `docs/step2_5_income_summary.md`。纯函数、Decimal。分支 `feature/step2_5-income-summary`,PR 到 main,CI 绿。
- **Claude**:本设计 + 手算黄金值;实现后逐分核对 + 查计算链(尤其不重复减标准扣除)+ 州税估算标注到位。
- **Shaw**:合并 PR。

## 8. 之后
Step 5.4 自雇前端接 `income_tax_summary`,展示完整自雇总税(联邦+SE 精确、州税标估算);REQ-011 后续精确化州税;REQ-009 把 W-2/RSU/海外/加密 也并进合并计税。
