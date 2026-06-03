# Step 2.9 设计文档 — REQ-009 Block 3：合并计税加海外赚取收入(FEIE 税率叠加)

日期：2026-06-03
阶段：PLM 阶段 2（Design）
依据：REQ-009 方案、**Block 1(step2_7)+ Block 2(step2_8)**、现有 `feie_estimate`(已在 main)、IRS Form 2555 + Foreign Earned Income Tax Worksheet + §911 + §1411
分支：`feature/step2_9-combined-feie`(基于 **Block 2 合并后的 main**)
角色：Claude 出设计 + 已逐分验证的黄金值;Codex 实现;Shaw 拍板。
工程标准:见 `coding_standards.md` §六(复用 / 抗并发 / 幂等 / 不给假数);规则只加载一次。

> 目标:在 Block 1+2 基础上并入**海外赚取收入(FEIE)**——豁免至上限,但剩余收入按 **Form 2555 税率叠加**(豁免额"垫底",非豁免部分按"含豁免额"的边际档计);**NIIT 的 MAGI 加回 FEIE 豁免额**(§1411)。复用 `feie_estimate` 算豁免。新增参数(keyword-only)默认 0 → **向后兼容**(foreign=0 必须逐分复现 Block 2,已验证)。

---

## 0. 关键设计点(都已验证)
1. **FEIE 税率叠加(§7,Form 2555 工作表)**:`federal = bracket(ordinary_taxable + exclusion) − bracket(exclusion)`。豁免额垫在最底层,非豁免收入因此按更高边际档计(不享最低档)。`exclusion=0` 时退化为 Block 2 的 `bracket(ordinary_taxable)`。
2. **NIIT 的 MAGI 加回豁免额(§1411)**:`magi = AGI + exclusion`(缺省;或传 modified_agi)。**海外高收入者的投资净收益可能因加回而触发 NIIT**(Ex2:加回后 28 万 > 20 万 → NIIT 1140;不加回则 0)。
3. **海外赚取收入的归属**:加进 AGI、减豁免;非豁免部分留税。**不计入 QBI**(qbi_amount 仍仅 SE);**MVP 假设不计美国工资税**(海外雇主 W-2 常无美国 FICA;海外自雇/totalization 协定属边界,标注未建模)。
4. **复用 `feie_estimate`** 算豁免(含 330 天测试 + 上限);不合格(<330 天)→ 豁免 0 → 海外收入全额计税、无叠加优惠。

## 1. 函数契约(在 Block 2 之上再扩 `income_tax_summary`)
在已有 `*`(keyword-only)后加:`foreign_earned_income: float = 0.0`、`days_abroad: int = 0`。
`result` 新增:`foreign_earned_income`(回显)、`feie_excluded_income`、`foreign_tax_rate_stacking_applied`(bool);`federal_income_tax` 改为税率叠加值;`net_investment_income_tax` 的 MAGI 含加回。`total_tax` 不变结构(联邦已含叠加;foreign=0→旧值不变)。

## 2. 计算链(在 Block 1+2 之上;复用 feie_estimate / _bracket_tax_decimal / _long_term_capital_gains_tax)
```
exclusion = feie_estimate(foreign_earned_income, days_abroad).excluded_income   # 0 若 <330 天
AGI = max(0, w2 + net_profit + other + st + lt + (foreign_earned_income − exclusion) − above_line)
qbi_amount = max(0, net_profit − above_line)                                    # 海外不进 QBI
taxable_total = max(0, AGI − deduction_used − QBI)
lt_taxed = max(0, min(lt, taxable_total)); ordinary_taxable = max(0, taxable_total − lt_taxed)
federal_income_tax = max(0, bracket(ordinary_taxable + exclusion) − bracket(exclusion))   # ★FEIE 税率叠加
long_term_capital_gains_tax = _long_term_capital_gains_tax(ordinary_stack=ordinary_taxable, long_term_gain=lt_taxed, ...)
nii = max(0, st + lt); magi = modified_agi 或 (AGI + exclusion)                  # ★NIIT 加回豁免额
niit = rate × min(nii, max(0, magi − NIIT阈值[filing]))
state = state_income_tax(...)            # 州税基用 AGI(注:多数州不认 FEIE → 州可能仍征,见 §4 边界)
total_tax = federal_income_tax + long_term_capital_gains_tax + total_payroll_tax + niit + state_tax
```

## 3. 黄金用例(参考实现逐分验证;含 foreign=0 复现 Block 2)
**Ex1 — 海外 200000, 330 天, single, 无其它:** exclusion 130000｜AGI 70000｜ordinary_taxable 55000｜**federal 13200.00**(=bracket(185000)−bracket(130000)=37247−24047)｜ltcg 0｜niit 0｜**total 13200.00**。
**Ex2 — 海外 200000(330d) + W2 50000 + 长期利得 30000, single:** exclusion 130000｜AGI 150000｜ordinary_taxable 105000｜**federal 28216.00**(税率叠加)｜ltcg 4500.00｜**niit 1140.00**(MAGI=150000+130000=280000 → 加回触发)｜total_payroll 3825.00(W2 FICA)｜**total 37681.00**。
**Ex3 — 回归 `foreign_earned_income=0`(W2 200000 + LT 50000):** federal 37247.00 / ltcg 7500.00 / niit 1900.00 / total **60465.20** = Block 2 Ex1。**(已验证。)**
边界:<330 天 → 豁免 0、海外全额计税、无叠加;海外 < 上限 → 全额豁免;FEIE 仅影响联邦档(州按 §4)。

## 4. 诚实边界(写进 assumptions)
- **州税与 FEIE**:多数州**不认** FEIE(无 §911 豁免)→ 州可能对海外收入仍征税。本块州税基用 AGI(已减豁免),属**简化**;州级 FEIE 不一致标注未建模(后续 REQ)。
- **FEIE × 长期利得合并工作表**:本 MVP 将 LTCG 叠在**豁免后** ordinary_taxable 上;当 FEIE 与大额长期利得同时存在时,IRS 合并工作表(Foreign Earned Income + QDCGT)可能略有差异 → 标注为简化。
- **海外工资税**:假设海外赚取收入不计美国 FICA/SE(海外雇主 W-2);海外自雇 + totalization 协定、住房豁免(housing exclusion)、bona fide residence 测试、FTC、被动海外收入(REQ-004)均**未建模**。
- FEIE 仅适用海外**赚取**收入(劳动/服务),不适用海外股息/利息/租金(那些走 FTC/NIIT,REQ-004)。

## 5. 验收(退出门槛)
- [ ] Ex1/2 逐分对齐(尤其税率叠加 federal、NIIT MAGI 加回触发);**Ex3 与 Block 2 逐分一致**;**foreign=0 且 gains=0 且 w2=0 仍复现最初 income_tax_summary**。
- [ ] FEIE 税率叠加正确(豁免垫底);NIIT MAGI 加回豁免额;海外不进 QBI、不计美国工资税(MVP)。
- [ ] 现有所有 golden/API 测试不变(新参数缺省零影响)。
- [ ] 纯函数、Decimal、复用 `feie_estimate`/`_bracket_tax_decimal`/`_long_term_capital_gains_tax`,规则只加载一次,不裸写、不给假数;不调 `federal_income_tax()`;不改 `feie_estimate`/`state_income_tax` 签名;income_tax_summary 保持 keyword-only。
- [ ] `assumptions` 完整标注 §4 各边界。
- [ ] ruff + unittest + 数据校验 + pip-audit + `git diff --check` 全绿;两份 index.html hash 不变。
- [ ] Claude 逐行(5 维)review + 逐分重算 Ex1/2/3 + 回归核对。

## 6. 交付物与分工
- **Codex**:`engine/tax_engine.py` 扩 `income_tax_summary`(加 foreign_earned_income/days_abroad;复用 feie_estimate;税率叠加;NIIT MAGI 加回;新 result 字段);`backend/schemas.py` 的 `IncomeSummaryRequest` 加这两字段(foreign ge=0,days 0..366);golden 加 Ex1/2 + foreign=0 回归;`test_engine.py` 边界(<330 天不合格、海外<上限全豁免、NIIT 加回触发、foreign=0 复现 Block 2);设计(本文件)+ 交付记录 docs/step2_9_combined_block3.md;更新 feature_status.md/product_backlog.md(REQ-009 Block 3,引擎三块齐)。分支 `feature/step2_9-combined-feie`(基于 Block 2 合并后的 main),PR→main,CI 绿。
- **Claude**:本设计 + 已验证黄金值;实现后逐行 review + 逐分重算 + 回归核对。
- **Shaw**:拍板、合并。

## 7. 之后
引擎三块(赚取/资本利得/海外)齐后 → **REQ-002 前端**:档案(收入桶/州/身份/海外天数)→ 一处调 `income_tax_summary` 算**总税**,取代各模块孤立相加。州级 FEIE、FTC、住房豁免、totalization 等列入后续 REQ。
> **依赖**:本块基于 Block 2。Codex prompt 待 **Block 2 合并到 main 后**再发。
