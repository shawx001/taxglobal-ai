# Step 2.8 设计文档 — REQ-009 Block 2：合并计税加资本利得(长期利得叠加 + NIIT)

日期：2026-06-03
阶段：PLM 阶段 2（Design）
依据：REQ-009 方案、**Block 1(step2_7,W-2+自雇合并)**、现有 `crypto_gain_estimate` 的 `_long_term_capital_gains_tax` + NIIT 数据(`us_capital_gains.json`)、IRS QDCGT 工作表 / §1(h) / §1411
分支：`feature/step2_8-combined-capital-gains`(基于 **Block 1 合并后的 main**)
角色：Claude 出设计 + 已逐分验证的黄金值;Codex 实现;Shaw 拍板。

> 目标:在 Block 1 基础上,把**资本利得**并入合并计税——**短期利得→普通收入**(并入累进),**长期利得→在普通应税收入之上按 0/15/20% 叠加**(§5),**NIIT 3.8% 按总 MAGI 过阈**(§6)。复用 crypto 引擎已验证的 LTCG 叠加 + NIIT 逻辑。新增参数默认 0 → **向后兼容**(gains=0 必须逐分复现 Block 1,已验证)。

---

## 0. 关键设计点
1. **短期利得 = 普通收入**:并入 AGI 与普通应税收入,按联邦档计(不享优惠),**不计 SE/FICA、不计 QBI**。
2. **长期利得叠加(§5,QDCGT)**:LT 在 AGI 内,但税额单独算——`ordinary_taxable = taxable_total − LT_taxed`,普通税按 `bracket_tax(ordinary_taxable)`;LT 按 `_long_term_capital_gains_tax(ordinary_stack=ordinary_taxable, long_term_gain=min(LT, taxable_total), LTCG档)`。复用 crypto 引擎的 helper。
3. **NIIT 按总 MAGI(§6)**:`nii = max(0, 短期 + 长期)`;`magi = modified_agi 或 AGI(近似,标注)`;`niit = 0.038 × min(nii, max(0, magi − 阈值[filing]))`。复用 `us_capital_gains.json` 的 NIIT 数据。
4. **州税**:利得在 AGI 内,**income-tax 州按普通收入征**(`_state_taxable_base(AGI)` 自然包含)→ 符合 REQ-012(多数州资本利得=普通收入)。**WA 的长期利得 excise 不在合并 summary 里建模**(WA 在 income_tax_summary 是 0 所得税;WA excise 仍走独立 crypto 模块)——标注为已知边界。
5. **净亏**:利得入参为净额;`max(0, ...)` 截至 0 → 净亏不产生负税、不计 $3000 抵扣/结转(沿用 crypto MVP,标注)。

## 1. 函数契约(在 Block 1 基础上再扩 `income_tax_summary`)
新增可选入参:`long_term_capital_gain: float = 0.0`、`short_term_capital_gain: float = 0.0`、`modified_agi: float | None = None`(NIIT 用;缺省取 AGI 并标注近似)。
`result` 新增:`long_term_capital_gains_tax`、`net_investment_income_tax`、`short_term_capital_gain`/`long_term_capital_gain`(回显)、`ordinary_taxable_income`(普通部分)。`taxable_income` 改为**总应税收入**(含 LT);新增 `ordinary_taxable_income`=普通部分。`total_tax` 现含 LTCG + NIIT(gains=0 时为 0 → 旧值不变)。

## 2. 计算链(在 Block 1 之上)
```
# Block 1 已得:合并工资税、above_line、qbi_amount(仅 SE)
AGI = max(0, w2 + sep + other + max(0,st_gain) + max(0,lt_gain) − above_line)
taxable_total = max(0, AGI − deduction_used)
QBI = qbi_deduction(qbi_amount, taxable_total, ...).deduction       # QBI 上限用 taxable_total
taxable_total = max(0, taxable_total − QBI)
lt_taxed = max(0, min(lt_gain, taxable_total))
ordinary_taxable_income = max(0, taxable_total − lt_taxed)
federal_income_tax = bracket_tax(ordinary_taxable_income, 联邦档[filing])   # 仅普通部分
long_term_capital_gains_tax = _long_term_capital_gains_tax(ordinary_stack=ordinary_taxable_income,
                                  long_term_gain=lt_taxed, brackets=LTCG档[filing])
nii = max(0, max(0,st_gain)+max(0,lt_gain)); magi = modified_agi or AGI
net_investment_income_tax = 0.038 × min(nii, max(0, magi − NIIT阈值[filing]))
state = state_income_tax(state_code, _state_taxable_base(...AGI...), filing)   # 利得按普通收入入州基
total_tax = federal_income_tax + long_term_capital_gains_tax + total_payroll_tax
            + net_investment_income_tax + state_tax
```

## 3. 黄金用例(参考实现逐分验证;含 gains=0 复现 Block 1)
**Ex 1 — W-2 200000 + 长期利得 50000, single, 无自雇, 无州:**
AGI 250000｜taxable_total 235000｜ordinary_taxable 185000｜federal 37247.00｜**LTCG 7500.00**(50000×15%)｜**NIIT 1900.00**(min(50000, 250000−200000)×3.8%)｜total_payroll 13818.20(W-2 FICA)｜**total_tax 60465.20**。

**Ex 2 — W-2 150000 + 自雇净 50000 + 长期利得 40000, single, 无州:**
AGI 237712.26｜qbi 4692.55(相位淘汰区,引擎处理)｜taxable_total 218019.71｜ordinary_taxable 178019.71｜federal 35571.73｜**LTCG 6000.00**(40000×15%)｜**NIIT 1433.07**(=min(40000, 237712.26−200000=37712.26)×3.8% → 被 MAGI 超阈额截顶,非全额)｜total_payroll 16050.48｜**total_tax 59055.28**。

**Ex 3 — 回归:`long_term_capital_gain=0, short_term_capital_gain=0`** → 必须逐分复现 Block 1(W-2 150000+自雇 50000:federal 34407.75 / total 50458.23;LTCG 0 / NIIT 0)。**(已验证。)**

边界:短期利得→普通档(用 ST 例验);NIIT 全额(Ex 1)vs 截顶(Ex 2);LT 落 0% 档(低收入)；高 LT 入 20% 档。

## 4. 验收(退出门槛)
- [ ] Ex 1/2 逐分对齐;**Ex 3 与 Block 1 逐分一致**(关键回归);**gains=0 且 w2=0 仍复现最初的 `income_tax_summary`**。
- [ ] 短期利得进普通档、不计 SE/FICA/QBI;长期利得 QDCGT 叠加正确;NIIT 按总 MAGI 且 `min()` 截顶。
- [ ] 现有所有 golden/API 测试不变(新参数缺省零影响)。
- [ ] 纯函数、Decimal、复用 `_long_term_capital_gains_tax` + `us_capital_gains` NIIT 数据,不裸写;不调 `federal_income_tax()`;不改 `state_income_tax`/`crypto_gain_estimate` 签名。
- [ ] `assumptions` 标注:NIIT 的 MAGI 近似(建议传 modified_agi)、**WA 长期利得 excise 不在合并 summary(走独立 crypto)**、净亏不计 $3000/结转。
- [ ] ruff + unittest + 数据校验 + pip-audit + `git diff --check` 全绿;两份 index.html hash 不变。
- [ ] Claude 逐行(5 维)review + 独立逐分重算 Ex 1/2/3 + 回归核对。

## 5. 交付物与分工
- **Codex**:`engine/tax_engine.py` 扩 `income_tax_summary`(加 long/short_term_capital_gain、modified_agi;QDCGT 叠加;NIIT;新 result 字段);`backend/schemas.py` 的 `IncomeSummaryRequest` 加这三个字段(数值 `ge=0`,modified_agi 可空);golden 加 Ex 1/2 + gains=0 回归;`test_engine.py` 边界;设计(本文件)+ 交付记录;更新 `feature_status.md`/`product_backlog.md`(REQ-009 Block 2)。分支 `feature/step2_8-combined-capital-gains`(基于 Block 1 合并后的 main),PR→main,CI 绿。
- **Claude**:本设计 + 已验证黄金值;实现后逐行 review + 逐分重算 + 回归核对。
- **Shaw**:拍板、合并。

## 6. 之后
Block 3(FEIE 税率叠加,§7)。三块齐后做 REQ-002 前端:档案带入 W-2/自雇/RSU/加密/海外 → 一处算总税。
> **依赖**:本块基于 Block 1。Codex prompt 待 **Block 1 合并到 main 后**再发(从含 w2_wages 的 main 切分支)。
