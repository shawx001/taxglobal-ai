# Step 2.7 设计文档 — REQ-009 Block 1：赚取收入合并计税(W-2 + 自雇)

日期：2026-06-03
阶段：PLM 阶段 2（Design）
依据：REQ-009 方案(`req009_plan_combined_income_tax.md`)、现有 `income_tax_summary`、`us_fica.json`/`us_federal.json`/`us_qbi.json`、IRS Schedule SE / Form 8959 / §199A / §1401
分支：`feature/step2_7-combined-earned-income`(基于 main)
角色：Claude 出设计 + 已逐分验证的黄金值;Codex 实现;Shaw 拍板。

> 目标:扩 `income_tax_summary`,把 **W-2 工资 + 自雇净利 + 其它普通收入** 合并成正确的赚取收入总税——**累进叠加(收入税)+ 合并工资税(共享 SS 基数 + 单一附加医保阈值)+ QBI 排除 W-2 + 州税**。新增参数全默认 0 → **向后兼容**(`w2_wages=0` 必须逐分复现现有 `income_tax_summary`,已验证)。

---

## 0. 关键设计点(都是"算准"的坑,已验证)
1. **社保工资基数共享(§2)**:W-2 工资先占 SS 基数 \$176,100,自雇 SS 只对**剩余基数**征。`se_ss_base = max(0, min(se_net_earnings, 176100 − min(w2,176100)))`。→ W-2 高时自雇 SS 会**显著降低**(甚至为 0)。
2. **附加医保单一阈值(§3)**:`addl = max(0, (w2 + se_net_earnings) − threshold[filing]) × 0.9%`。**数学等价于** Form 8959 分别算 wages 与 SE 再相加(已证),用合并式即可。
3. **QBI 基数排除 W-2(§4)**:`qbi_amount = max(0, net_self_employment_profit − ½SE − se_health − retirement)`,**不含 W-2/其它**。
4. **½SE 先舍入到分再进 AGI**:现有引擎用的是 `self_employment_tax` 输出的**已 `_money` 舍入**的 deductible_half_se_tax;Block 1 必须 `half_se = _money_decimal(se_tax/2)` 后再算 AGI/QBI,否则 w2=0 会与现有差 1 分(已踩坑验证)。

## 1. 函数契约(扩 `income_tax_summary`,新增 `w2_wages`)
新增可选入参:`w2_wages: float = 0.0`(W-2 box-1/Medicare 工资;含已在 W-2 上的 RSU 归属值)。其余沿用。
> `other_ordinary_income`:其它普通应税收入(不再被 SE/FICA 计税的部分,如利息);仍作累进与州基。
`result` 新增:`w2_wages`、`w2_fica_tax`(W-2 员工 SS+Medicare)、`total_payroll_tax`(W-2 FICA + 自雇 SE + 附加医保)。`total_tax` 现含 `w2_fica_tax`(w2=0 时为 0 → 旧值不变)。

## 2. 合并工资税(新 helper `_combined_payroll`,复用 `us_fica` 费率;替换原 `self_employment_tax` 调用)
```
se_net_earnings = max(0, net_self_employment_profit) × 0.9235
w2 = max(0, w2_wages)
w2_ss_wages = min(w2, 176100); w2_ss = w2_ss_wages × 0.062            # 员工 SS
se_ss = max(0, min(se_net_earnings, 176100 − w2_ss_wages)) × 0.124    # 自雇 SS（共享基数）
w2_medicare = w2 × 0.0145;  se_medicare = se_net_earnings × 0.029
additional_medicare_tax = max(0, (w2 + se_net_earnings) − threshold[filing]) × 0.009
self_employment_tax = se_ss + se_medicare                            # 自雇 SE（不含附加医保）
deductible_half_se_tax = _money_decimal(self_employment_tax / 2)     # ★先舍入再进 AGI
w2_fica_tax = w2_ss + w2_medicare
total_payroll_tax = w2_fica_tax + self_employment_tax + additional_medicare_tax
```
（费率/基数/阈值全取 `us_fica.json`,不裸写。`w2=0` 时退化为现有 `self_employment_tax`。）

## 3. 收入税链(复用 `bracket_tax`/`qbi_deduction`/`_state_taxable_base`/`state_income_tax`)
```
above_line = deductible_half_se_tax + se_health_insurance + retirement_contributions
AGI = max(0, w2_wages + net_self_employment_profit + other_ordinary_income − above_line)
qbi_amount = max(0, net_self_employment_profit − above_line ... )    # 仅 SE:= sep − ½SE − se_health − retirement
deduction_used = deduction 或 标准扣除[filing]
taxable_before_qbi = max(0, AGI − deduction_used)
QBI = qbi_deduction(qbi_amount, taxable_before_qbi, filing, qbi_w2_wages, qbi_ubia, is_sstb).deduction
taxable_income = max(0, taxable_before_qbi − QBI)
federal_income_tax = bracket_tax(taxable_income, 联邦档[filing])     # 不调 federal_income_tax()
state = state_income_tax(state_code, _state_taxable_base(... AGI ...), filing)   # 复用 Step 2.5/1.4 机器
total_tax = federal_income_tax + total_payroll_tax + state_tax
quarterly_estimate = total_tax / 4
```

## 4. 黄金用例(我已写参考实现逐分验证;含 w2=0 复现自检)
**Ex A — W-2 150000 + 自雇净 50000, single, 无州:**
| 字段 | 值 |
|---|---|
| w2_ss / se_ss | 9300.00 / **3236.40**(共享基数后,非孤立 5725.70) |
| w2_medicare / se_medicare | 2175.00 / 1339.08 |
| additional_medicare_tax | 0.00（合计 196175 < 200000）|
| self_employment_tax（SE 部分）| 4575.48 |
| deductible_half_se_tax | 2287.74 |
| w2_fica_tax | 11475.00 |
| total_payroll_tax | 16050.48 |
| adjusted_gross_income | 197712.26 |
| qbi_deduction | 9542.45 |
| taxable_income | 173169.81 |
| federal_income_tax | 34407.75 |
| **total_tax** | **50458.23** |

**Ex B — W-2 250000 + 自雇净 60000, single, 无州（测满基数+附加医保+QBI 淘汰）:**
se_ss **0.00**（W-2 占满 SS 基数）、additional_medicare **948.69**、qbi **0.00**（taxable 294196.55 > 单身上限 247300 且无 QBI 工资/UBIA → 工资上限=0）、self_employment_tax 1606.89、w2_fica 14543.20、total_payroll 17098.78、AGI 309196.55、taxable 294196.55、federal 72516.04、**total_tax 89614.82**。

**Ex C — 向后兼容:`w2_wages=0, net_self_employment_profit=100000, single`** 必须逐分等于现有 `income_tax_summary(100000)`：AGI 92935.22 / qbi 15587.04 / taxable 62348.18 / federal 8630.60 / se_tax 14129.55。**(已验证 MATCH。)**

州税路径:沿用 Step 2.5/1.4 的 `_state_taxable_base`+`state_income_tax`(对合并 AGI),Codex 实现后我加 CA 例逐分核。

## 5. 验收(退出门槛)
- [ ] Ex A/B 逐分对齐;**Ex C 与现有 `income_tax_summary(100000)` 逐分一致**(关键回归)。
- [ ] **现有黄金/测试不变**(自雇/income-summary 的 golden、API 测试;`w2_wages` 缺省时行为零变化)。
- [ ] 纯函数、Decimal、费率全来自 `us_fica.json`/`us_federal.json`(不裸写);不调 `federal_income_tax()`;不改 `state_income_tax` 签名。
- [ ] 共享 SS 基数、单一附加医保阈值、QBI 排除 W-2、½SE 先舍入 —— 四个坑都按 §0/§2/§3 实现。
- [ ] `assumptions` 标注:W-2 假设含 RSU 归属值;`other_ordinary_income` 近似;残余项(AMT/期权/被动海外等)未建模。
- [ ] ruff + unittest + 数据校验 + pip-audit + `git diff --check` 全绿;两份 index.html hash 不变(本步不碰前端)。
- [ ] Claude 逐行(5 维)review + 独立逐分重算 Ex A/B/C + 确认旧 golden 未变 + SCALE(纯函数/规则已缓存,无新热路径 I/O)。

## 6. 交付物与分工
- **Codex**:`engine/tax_engine.py` 加 `_combined_payroll` + 扩 `income_tax_summary`(加 `w2_wages`、替换 SE 调用为合并工资税、QBI 排除 W-2、新增 result 字段、total 含 w2_fica);`backend/schemas.py` 的 `IncomeSummaryRequest` 加 `w2_wages: float = Field(default=0, ge=0)`;`tests/golden/income_tax_summary.json` 加 Ex A/B + w2=0 回归;`tests/test_engine.py` 边界(满 SS 基数、附加医保触发、QBI 淘汰、w2=0 复现);设计(本文件)+ 交付记录 `docs/step2_7_combined_block1.md`;更新 `feature_status.md`/`product_backlog.md`(REQ-009 Block 1 进行中)。分支 `feature/step2_7-combined-earned-income`,PR→main,CI 绿。
- **Claude**:本设计 + 已验证黄金值;实现后逐行 review + 逐分重算 + 回归核对。
- **Shaw**:拍板、合并。

## 7. 之后
Block 2(长期利得叠加 + NIIT 按总 MAGI)、Block 3(FEIE 税率叠加)。前端(REQ-002:档案带入 W-2/自雇/... 一处算总税)在引擎块齐后做。
