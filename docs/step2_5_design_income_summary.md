# Step 2.5 设计文档（revised）— `income_tax_summary`（自雇总税，州税精确化）

日期：2026-06-02（revised；取代 1.4 之前“联邦应税收入当州税基”的估算版）
阶段：PLM 阶段 2（Design）
依据：Step 2/2.1/2.4 引擎、**Step 1.4 州税基数据（`us_states.json` 各州 `tax_base`）**、`tax_rules_self_employment.md`、IRS §1401/§164(f)/§199A/§63、各州 DOR
分支：`feature/step2_5-income-summary`（基于 **1.4 合并后的 main**）
角色：Claude 出设计 + 已查证黄金值（独立用引擎逐分核对）；Codex 实现、开 PR、合并；Shaw 拍板。

> 目标：把零散引擎串成**自雇总税**——SE 税 + ½SE 抵扣 + QBI + 标准扣除 + 联邦累进 + **精确州税**。**联邦 + SE 精确；州税改为按 Step 1.4 的 `tax_base` 精确计算**（起点 + 州标准扣除/免税额 + QBI 一致性），不再标“估算”。各州残余特定加减项/抵免仍标注未建模。复用现有引擎、Decimal、不裸写税率。

---

## 0. 本次修订相对旧版的变化（为什么）
- 旧版州税 = `state_income_tax(州, 联邦最终 taxable)`，把联邦应税收入当州税基 → **CA 估算 $2,371.90**，明确标“估算”。
- Step 1.4 已为 CA/NY/IL/CO/GA 补 `tax_base`（起点 / 州标准扣除或免税额 / QBI 一致性）。
- 本步用 `tax_base` 算**真实州税基** → **CA $4,550.96**。同口径差 **$2,179.06（近一倍）**，计算产品不能接受。
- **REQ-011 状态**：核心州税基已精确（🟢→🟡）；残余未建模项命中时 `assumptions` 标注（见 IS-7）。

## 1. 函数契约
```
income_tax_summary(
    net_self_employment_profit: float = 0.0,
    other_ordinary_income: float = 0.0,     # 预留(W-2 等)，本步默认 0
    filing_status: str = "single",
    state_code: str | None = None,
    se_health_insurance: float = 0.0,        # above-line 扣除
    retirement_contributions: float = 0.0,   # SEP/Solo401k，above-line
    qbi_w2_wages: float = 0.0, qbi_ubia: float = 0.0, is_sstb: bool = False,
    deduction: float | None = None,          # None=联邦标准扣除
    tax_year: int = 2025,
) -> dict
```
`result` 含：`self_employment_tax`、`additional_medicare_tax`、`deductible_half_se_tax`、`adjusted_gross_income`、`deduction_used`、`qbi_deduction`、`taxable_income`、`state_taxable_base`（**新增**，便于审计/前端展示）、`state_income_tax`（含 tax / rate / not_covered 标记）、`federal_income_tax`、`total_tax`、`quarterly_estimate`。

## 2. 计算链（复用引擎，Decimal，组合各引擎的 _money 结果）
```
SE = self_employment_tax(net_self_employment_profit, filing)        # §1401
above_line = SE.deductible_half_se_tax + se_health_insurance + retirement_contributions
agi = max(0, net_self_employment_profit + other_ordinary_income − above_line)
ded = deduction if 提供 else 联邦标准扣除[filing]          # us_federal.standard_deduction
taxable_before_qbi = max(0, agi − ded)
qbi_amount = max(0, agi − other_ordinary_income)            # QBI 只算经营收入部分
QBI = qbi_deduction(qbi=qbi_amount, taxable_income=taxable_before_qbi, filing,
                    w2_wages=qbi_w2_wages, ubia=qbi_ubia, is_sstb=is_sstb).deduction
taxable_income = max(0, taxable_before_qbi − QBI)
federal_income_tax = bracket_tax(taxable_income, us_federal.ordinary_income_brackets[filing])
                                                            # IS-4：不调 federal_income_tax()，避免重复减标准扣除
# —— 州税（精确，走 tax_base；见 §3 helper）——
state_base = _state_taxable_base(state_block, agi, taxable_income, QBI, filing)   # 无 tax_base 时回退 taxable_income
state_result = state_income_tax(state_code, state_base, filing)   # 复用现有函数：拿 tax + citations + not_covered
state_tax = state_result.result.tax if state_result.status == "ok" else 0
total_tax = SE.self_employment_tax + SE.additional_medicare_tax + federal_income_tax + state_tax
quarterly_estimate = total_tax / 4                          # §6654
```
NIIT 不计（积极自雇非投资收益）。

## 3. 州税精确化设计（关键决策）
**IS-STATE（取代旧 IS-5）：不改 `state_income_tax` 签名。** 它是公开 API（`/calc/state-income`，schema `state_code/taxable_income/filing_status`）、前端收入税模块在用、黄金测试依赖——改签名是破坏性变更。改为：`income_tax_summary` 内部用纯 helper 算出 `state_base`，再把它当 `taxable_income` 喂给现有 `state_income_tax`（它本就“对传入基数套 brackets/flat”），从而**零破坏地复用其 flat/progressive 计算 + citations + not_covered/status 处理**。

新增纯 helper（`engine/tax_engine.py`，Decimal）：
```
_state_taxable_base(state_block, *, federal_agi, federal_taxable_income, federal_qbi_deduction, filing) -> Decimal:
    tb = state_block.get("tax_base")
    if tb is None: return federal_taxable_income            # 回退（无 tax_base 的州，保持旧行为）
    if tb["start_from"] == "federal_taxable_income":         # CO
        return federal_taxable_income + (federal_qbi_deduction if tb.get("qbi_addback") else 0)
    # start_from == "federal_agi"（CA/NY/GA/IL）
    if tb.get("uses_exemption_allowance"):                   # IL
        count = 2 if filing == married_filing_jointly else 1 # 假设：mfj=2，其余=1；受养人不建模
        phaseout = tb["exemption_phaseout_agi"][filing]
        allowance = 0 if federal_agi > phaseout else tb["exemption_allowance_per_person"] * count
        return max(0, federal_agi − allowance)
    return max(0, federal_agi − tb["standard_deduction"][filing])   # CA/NY/GA
    # 所有州 allows_qbi=false：federal_agi 起点本就不含 QBI，无需另减；CO 已显式加回
```
州税分流（`income_tax_summary` 内）：
- `income_tax_type == "none"`（FL/WA/NV）：`state_income_tax` 返回 tax=0（rate 0），state_base 不影响结果。
- `income_tax_type ∈ {flat, progressive}` 且 `effective`（CA/NY/GA/IL/CO）：用上面的 `state_base`，精确到分。
- `status ∈ {source_pending, ...}`（MA/TX）或未知州码：`state_income_tax` 返回 not_covered → 总税仅含联邦+SE，并在字段/assumptions 诚实提示“该州税未覆盖”。

## 4. 黄金用例（已用引擎逐分核对）
**公共部分（net 100000, single）：** SE 14129.55｜additional_medicare 0.00｜deductible_half_se 7064.78｜AGI 92935.22｜standard_deduction 15000｜taxable_before_qbi 77935.22｜qbi_deduction 15587.04｜taxable_income 62348.18｜federal_income_tax 8630.60｜联邦+SE 小计 22760.15。

| 州 | 类型 | state_base 规则 | state_base | state_income_tax | **total_tax** |
|---|---|---|---|---|---|
| FL / WA / NV | none | — | — | 0.00 | **22760.15** |
| CA | progressive | AGI − 5706 | 87229.22 | 4550.96 | 27311.11 |
| NY | progressive | AGI − 8000 | 84935.22 | 4527.86 | 27288.01 |
| GA | flat 5.19% | AGI − 12000 | 80935.22 | 4200.54 | 26960.69 |
| IL | flat 4.95% | AGI − 2850（1 人免税额） | 90085.22 | 4459.22 | 27219.37 |
| CO | flat 4.40% | 联邦taxable 62348.18 + QBI 15587.04 | 77935.22 | 3429.15 | 26189.30 |
| MA / TX | source_pending | not_covered | — | not_covered | 22760.15（仅联邦+SE，诚实标注）|

**Case 2 — net 10000, single, FL（收入低于标准扣除）：** SE **1412.96**、deductible_half_se 706.48、AGI 9293.52、taxable 0、federal 0.00、**total 1412.96**、quarterly 353.24。→ 演示“收入低于标准扣除仍欠 SE 税”。

> Case 1 全部 7 行（含 CA/NY/GA/IL/CO 精确州税）与 Case 2 均为我用引擎独立逐分核算的结果。Codex 实现后我会再独立重算逐分对齐。

## 5. 设计决策
- **IS-1** 本步聚焦自雇；`other_ordinary_income` 预留默认 0（将来 REQ-009 扩成全收入合并计税）。
- **IS-2** 复用引擎、组合其 _money 输出求和（确定、不重复推导）；全程 Decimal。
- **IS-3** QBI 输入 = 经营收入（agi − other_ordinary_income）；QBI 整体上限用 taxable_before_qbi。
- **IS-4** 联邦税用 `bracket_tax(最终 taxable)`，**不调 `federal_income_tax()`**（它会再减一次标准扣除，重复）。
- **IS-STATE** 见 §3：不改 `state_income_tax` 签名；helper 算 state_base 后复用之。
- **IS-6** NIIT 不计（N/A 自雇积极收入）。
- **IS-7（诚实边界）** 州税基已精确到“起点 + 州标准扣除/免税额 + QBI 一致性”；但**各州残余特定调整未建模**：NY tax benefit recapture（NYAGI>$107,650）、IL/GA 退休收入减项/exclusion、CA Schedule CA 调整、年龄/盲人额外扣除、州级抵免、IL 受养人免税额数（本步按申报身份假设 mfj=2、其余=1）。命中时 `assumptions` 必须标注“该州存在未建模的特定调整，州税可能偏差”。

## 6. Backlog 更新（REQ-011）
```
| REQ-011 | 州级税基一致性 | 州数据+引擎 | 🟡 | 核心税基已精确（Step 1.4 数据 + Step 2.5 helper：起点/州标准扣除/免税额/QBI 一致性）。残余未建模：NY recapture、IL/GA 退休减项、CA Schedule CA、年龄/盲人额外扣除、州级抵免、IL 受养人数。命中时引擎 assumptions 标注。 |
```

## 7. 验收（退出门槛）
- [ ] 独立重算 Case 1 全部 7 行 + Case 2 **逐分对齐**（尤其 CA 4550.96 / FL 22760.15 / Case2 1412.96；CO=联邦taxable+QBI 加回 77935.22）。
- [ ] 纯函数、Decimal、复用引擎；**不裸写税率/阈值**（grep 校验：州税基数值全来自 `us_states.json` 的 `tax_base`，标准扣除来自 `us_federal.json`）。
- [ ] **不调 `federal_income_tax()`**（避免重复减扣除）；**不改 `state_income_tax` 签名**。
- [ ] `state_base` 取数正确：CA/NY/GA=AGI−州std；IL=AGI−免税额（含 phaseout 与 mfj=2 假设）；CO=联邦taxable+QBI 加回。
- [ ] not_covered 州（MA/TX）+ 未知州码：总税仅联邦+SE 且 assumptions 诚实标注；零税州（FL/WA/NV）total 精确。
- [ ] ruff + unittest + 数据校验(`validate_step1_data.ps1`) + pip-audit CI 全绿；**根 index.html hash 未变**（`833508998A7FF1C783646E5E8B35E8C66AB27AE5FF88193318C2A1F2007B4B69`）。
- [ ] Claude review 通过（[Blocker]/[Major]/[Minor]/[Nitpick]），重点：计算链顺序、QBI/标准扣除交互、state_base 对每个州是否用对税基。

## 8. 交付物与分工
- **Codex**：
  - `engine/tax_engine.py`：加 `income_tax_summary` + 纯 helper `_state_taxable_base`（复用 self_employment_tax/qbi_deduction/bracket_tax/state_income_tax）；`engine/__init__.py` 导出 `income_tax_summary`。
  - `tests/golden/income_tax_summary.json`：Case 1 的 FL/CA/NY/GA/IL/CO/MA 七行 + Case 2；`tests/test_engine.py` 边界（低收入、not_covered 州、未知州码、CO 加回路径）。
  - `product_backlog.md`：按 §6 更新 REQ-011 为 🟡。
  - 设计文档（本文件）+ 交付记录 `docs/step2_5_income_summary.md`；更新 `feature_status.md`（`income_tax_summary` 行 ⬜→✅，Step=2.5，设计文档=本文件，实现 commit，官方来源）。
  - 分支 `feature/step2_5-income-summary`（基于 1.4 合并后的 main），PR→main，CI 绿。纯函数、Decimal。
- **Claude**：本设计 + 已查证黄金值；实现后逐分核对 + 查计算链（不重复减扣除、state_base 取数正确、not_covered 诚实）。
- **Shaw**：拍板。

## 9. 之后
Step 5.4 自雇前端接 `income_tax_summary`，展示**联邦+SE+州全精确**的自雇总税（zero-tax 州/未覆盖州诚实提示）；REQ-011 残余州级调整后续精确化；REQ-009 把 W-2/RSU/海外/加密并进合并计税（`other_ordinary_income` 已预留）。
