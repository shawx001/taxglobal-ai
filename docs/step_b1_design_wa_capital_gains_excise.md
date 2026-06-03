# Step B1 设计文档 — WA 资本利得 excise 接进合并计税(DRY 复用)

日期：2026-06-03
阶段：PLM 阶段 2（Design）/ Step B 扩州(第 1 子步)
依据：`us_states.json` WA 已有 `capital_gains_excise` 数据(REQ-012);`engine/crypto.py` `_crypto_state_tax` 已实现 WA excise 计算;`engine/state.py`(Step A.5 后)。
分支：`feature/step-b1-wa-excise`(基于 #26 合并后的 main)
角色：Claude 出设计 + 已验证黄金值;Codex 实现;Shaw 拍板。
工程标准：**DRY**——抽共享 helper,crypto 与 summary 共用,不复制逻辑;数值精确第一;WA excise 作为**声明式 state 规则类型**,不写特判分支堆进 summary。

> 目标:修复 Step A 我对账标出的缺口——WA 居民有大额长期利得时,合并总览州税显示 \$0(因 WA `income_tax_type=none`),但 WA 实际对长期资本利得征 excise(7%/9.9%,\$278,000 标准扣除)。本步把**已存在**的 WA excise 计算抽成共享 helper,接进 `income_tax_summary`,使 WA 长期利得正确计税。

---

## 0. 现状与缺口
- `us_states.json` WA：`income_tax_type:none` + `capital_gains_excise {rate 0.07, surtax_rate 0.029, surtax_threshold 1000000, standard_deduction 278000, long_term_only true}`,标 `state_parameter_year:2025`。
- `engine/crypto.py _crypto_state_tax`：已读 `capital_gains_excise` 并对净长期利得算 excise(crypto 路径已用,有 golden)。
- `engine/state.py state_income_tax`：只按 flat/none/progressive 对单一"应税额"算 → WA(none)返回 \$0,**不碰 excise**。
- `income_tax_summary` 州路径：`_state_taxable_base` + `state_income_tax` → WA 得 \$0,长期利得的 excise**漏算**。

## 1. 设计(DRY:抽共享 helper + 接进 summary)
1. **抽共享 helper** 到 `engine/state.py`(行为与现 crypto 实现一致):
   ```
   def state_capital_gains_excise(state_block, *, net_long_term_gain: Decimal) -> dict|None:
       cge = state_block.get("capital_gains_excise")
       if not cge: return None
       std    = _decimal_rule(cge["standard_deduction"])
       rate   = _decimal_rule(cge["rate"])            # 0.07
       surr   = _decimal_rule(cge["surtax_rate"])     # 0.029（即 >阈值部分 7%+2.9%=9.9%）
       thr    = _decimal_rule(cge["surtax_threshold"])# 1,000,000
       taxable = max(0, net_long_term_gain - std)
       base_part = min(taxable, thr); surtax_part = max(0, taxable - thr)
       tax = base_part*rate + surtax_part*(rate+surr)
       return {"tax": tax, "taxable_capital_gains": taxable, "rate": rate, ...}
   ```
   计算公式必须**与现 `_crypto_state_tax` 里 WA 分支逐分一致**(抽取而非重写);`crypto._crypto_state_tax` 改为调用此 helper(去重),**crypto 现有 golden 必须逐分不变**。
2. **接进 `income_tax_summary` 州路径**:取得 state_block 后,除现有 income-tax(WA=0)外,若 `state_block` 有 `capital_gains_excise` 且 `long_term_capital_gain>0`,用 helper 对 `long_term_capital_gain`(净长期利得,`long_term_only`)算 excise。
3. **总税与展示**:`total_tax` 计入州 excise;`result` 加 `state_capital_gains_excise` 字段;breakdown 加一行「州资本利得税(excise)」;州 income-tax 行仍显示(WA=0)。`assumptions` 标注:仅净长期利得、假设非豁免资产(房产/退休账户除外)、假设 WA 居民 + 州内归属(沿用 crypto 口径)。
4. **数据驱动,不特判**:summary 不写 `if state=='WA'`;一律走"state_block 有 capital_gains_excise 就算"的声明式逻辑——未来别的州若有类似 excise,加数据即可。

## 2. 不在本步做
- **不**做 NJ/OR/PA(所得税州,需扩 gross-income / 联邦减项 / flat 税基)→ Step B2。
- **不**改 WA excise 的参数/公式(沿用已核验的 2025 DOR 值,标 `state_parameter_year:2025`)。
- **不**改其它州、联邦、前端。

## 3. 已验证黄金值(单身,2026 联邦 + WA 2025 excise;我已独立交叉,与调研 WA 算例一致)
- **WA-1**:`long_term_capital_gain=500000, state_code="WA"` →
  联邦 income 0｜LTCG tax 65,167.50｜NIIT 11,400.00｜**WA excise 15,540.00**(=7%×(500,000−278,000),<\$1M 无 surtax)｜**total 92,107.50**。
- **WA-2(低于扣除)**:`long_term_capital_gain=200000, state_code="WA"` →
  LTCG tax 20,167.50｜NIIT 0｜**WA excise 0**(200,000<278,000)｜**total 20,167.50**。
- **WA-3(短期不计 excise)**:`short_term_capital_gain=300000, state_code="WA"` → WA excise 0(long_term_only);短期按普通税率联邦计。
- **crypto 回归**:WA crypto 现有 golden 抽 helper 后逐分不变。
（数值实现后由 Claude 逐分重算锁定;Codex 先按公式实现。)

## 4. 验收门槛
- [ ] WA-1/2/3 逐分命中;crypto WA golden 逐分不变(helper 抽取行为不变)。
- [ ] summary 数据驱动(无 `state=='WA'` 特判);WA income-tax 行仍 0,excise 单列且计入 total。
- [ ] 非 WA 州 + 无 excise 的州:summary 行为完全不变(回归)。
- [ ] ruff + unittest + 数据校验 + `git diff --check` 全绿;两份 index.html hash 不变(本步不动前端)。
- [ ] Claude 逐分重算 WA-1/2/3 + 回归 crypto WA + 抽查非 excise 州不变。

## 5. 交付物与分工
- **Codex**:`engine/state.py` 加 `state_capital_gains_excise` 共享 helper;`engine/crypto.py` 改调该 helper(去重,行为不变);`engine/summary.py` 州路径接 excise + 新 result 字段/breakdown 行 + assumptions;golden 加 WA-1/2/3;交付记录 `docs/step_b1_wa_excise.md`;更新 `feature_status.md`/`product_backlog.md`。分支 `feature/step-b1-wa-excise`,PR→main,CI 绿。
- **Claude**:本设计 + 已验证黄金值;实现后逐分重算 + crypto 回归 + 数据驱动核查。
- **Shaw**:拍板、合并。

## 6. 之后
Step B2：NJ(gross-income 税基 + \$1,000 免税额)/ OR(联邦税减项 + OR 标准扣除)/ PA(flat 3.07% + 无扣除 gross 基)——扩 `_state_taxable_base` 的税基形状(新 `start_from`/减项配置),数据驱动。
Step C：前端 RSU 独立桶 + 发 `tax_year=2026`。
