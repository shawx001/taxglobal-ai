# Step 2.2 设计文档 — crypto_gain_estimate(逐笔成本基匹配 + 资本利得估税)

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：`engineering_process.md`、`coding_standards.md`、`data/tax_years/2025/us_capital_gains.json`、`us_federal.json`、`us_fica.json`
分支：`feature/step2_2-crypto`
角色：Claude 出设计 + 查证税务规则；Codex 实现；RSU 留到 Step 2.3。

> 范围（已确认）：**完整逐笔 lot 匹配引擎**。原型里的 `mult:0.55 / *0.4 / *0.20` 是 demo 假数，不得搬入。本步只做引擎函数 + 黄金测试，不碰前端/API。

---

## 1. 函数契约

```
crypto_gain_estimate(
    lots: list[dict],                 # 买入批次 [{asset, date, quantity, cost_basis}]，cost_basis=该批总成本
    disposals: list[dict],            # 卖出事件 [{asset, date, quantity, proceeds}]，proceeds=该笔总收入
    method: str = "FIFO",             # "FIFO" | "LIFO" | "HIFO"
    filing_status: str = "single",
    other_taxable_income: float = 0.0,  # 其他应税收入(普通)，用于把资本利得叠到正确税档
    modified_agi: float | None = None,  # NIIT 用；缺省则按 §4 近似
    tax_year: int = 2025,
) -> dict
```
返回沿用 8 键统一结构。`result`：
```
{
  "method": "FIFO",
  "realized": {
    "short_term_gain": <净短期，可负>,
    "long_term_gain":  <净长期，可负>,
    "net_capital_gain": <Schedule D netting 后的合计>
  },
  "lots_matched": [   # 8949 风格逐笔行
    {"asset","quantity","acquired","sold","proceeds","cost_basis","gain","term":"short"|"long"}
  ],
  "tax_estimate": {
    "short_term_ordinary_tax": <净短期增量普通税>,
    "long_term_capital_gains_tax": <叠加后 LTCG 税>,
    "net_investment_income_tax": <NIIT>,
    "total": <三者合计>
  }
}
```
`rule_version`：本函数用多源，放 `["us-2025-capital-gains-v0.1","us-2025-federal-v0.1"]`（或单 `rule_version` + `rule_versions` 列表，二选一，实现时统一）。`citations` 取 capital_gains + federal 的 source_ids。

---

## 2. 输入校验（防御性，违规→ status `invalid_input` + reason，不抛栈给前端）

- `method` ∈ {FIFO,LIFO,HIFO}，否则 invalid_input。
- 每个 lot/disposal：`quantity>0`、`cost_basis>=0`、`proceeds>=0`、`date` 可解析（ISO `YYYY-MM-DD`）、`asset` 非空。
- **超卖检查**：某 asset 的累计卖出数量 > 累计买入数量 → invalid_input（reason 指明 asset 与缺口）。这是最常见脏数据，必须显式拦，不能静默。
- `filing_status` 经现有 `_normalize_filing_status`（含 alias）。

> 用 `invalid_input` 而非 `not_covered`：后者表示"知识库没覆盖"，这里是"用户数据有问题"，语义要分开（呼应 coding_standards 异常分类）。

---

## 3. 成本基匹配算法（核心，确定性）

1. 按 `asset` 分组；跨 asset 不相互匹配（BTC 卖只能配 BTC 买）。
2. 每组内把 lots 按 method 排序消耗：
   - **FIFO**：acquisition date 升序（最早先出）
   - **LIFO**：acquisition date 降序（最晚先出）
   - **HIFO**：单位成本（cost_basis/quantity）降序（最贵先出）
3. disposals 按 date 升序处理；每笔从排序后的 lots 逐个消耗，支持**部分消耗**（一笔卖出可跨多个 lot；一个 lot 可被多笔卖出分次消耗）。
4. 每个 match 产出一行：
   - proceeds 行额 = 该笔卖出单价 × 本次匹配数量（单价 = disposal.proceeds / disposal.quantity）
   - cost 行额 = 该 lot 单位成本 × 本次匹配数量
   - gain = proceeds 行额 − cost 行额
   - **持有期**：`sold_date > acquired_date + 1 年` → `long`，否则 `short`（IRS：持有"超过一年"为长期；用日历年加法，非 365 天，处理闰年）
5. 全程 **Decimal**（金额、单价、数量都用 Decimal；数量可能小数如 0.5 BTC）。

### 3.1 匹配黄金例（确定性，无舍入歧义）
数据集 D（单一 asset=BTC）：
- lot A：2023-01-10 买 1.0，cost 20000
- lot B：2024-06-01 买 1.0，cost 40000
- 卖出：2025-03-01 卖 1.5，proceeds 75000（单价 50000/BTC）

| method | 匹配 | 结果 |
|---|---|---|
| **FIFO** | 1.0×A(LT) + 0.5×B(ST) | LT gain **30000**(50000−20000)，ST gain **5000**(25000−20000) |
| **HIFO** | 1.0×B(ST) + 0.5×A(LT) | ST gain **10000**(50000−40000)，LT gain **15000**(25000−10000) |
| **LIFO** | 1.0×B(ST) + 0.5×A(LT) | 同 HIFO 本例(因 B 更晚且更贵)：ST **10000**，LT **15000** |

→ 黄金固化 realized.short_term_gain / long_term_gain；FIFO 总利得 35000，HIFO/LIFO 25000，演示节税差异（这是产品卖点，且全部真实计算）。

---

## 4. 税额估算算法（叠加 stacking + NIIT）

资本利得税率取决于"含利得后的总应税收入"，必须做 stacking：

1. **Schedule D netting**：`net_st`、`net_lt` 各自求和；若一正一负互相抵销（净短期亏抵净长期盈，反之亦然），得 `net_st'`、`net_lt'`。
2. **净亏处理（MVP 简化，明确标注）**：若总净为亏 → `tax_estimate` 全 0，`assumptions` 注明"最多 $3,000 可抵普通收入、余额结转后续年度，本函数不计算（需整表上下文）"。**不伪造**。
3. **短期增量普通税**：把净短期盈当普通收入叠在 `other_taxable_income` 之上：
   `st_tax = bracket_tax(other_taxable_income + net_st') − bracket_tax(other_taxable_income)`（用 `us_federal` 普通档）。
4. **长期 LTCG 税（stacking）**：长期盈坐落在 `ordinary_stack = other_taxable_income + max(0,net_st')` 之上，按 `us_capital_gains` 的 LTCG 断点对 `[ordinary_stack, ordinary_stack+net_lt']` 这一段切档计税（0%/15%/20% 按落入的断点）。
5. **NIIT**：`nii = max(0, net_st' + net_lt')`（净投资收益，仅取正）；`magi = modified_agi if 提供 else other_taxable_income + nii`（**近似，标 assumption**）；`niit = 0.038 × min(nii, max(0, magi − threshold[filing]))`。
6. `total = st_tax + ltcg_tax + niit`。全程 Decimal，展示字段 `_money` 量化。

### 4.1 税额黄金例（FIFO 数据集 D，single，other_taxable_income=100000）
- net_st'=5000，net_lt'=30000
- st_tax = bracket(105000) − bracket(100000)：(103350−100000)×.22 + (105000−103350)×.24 = 737 + 396 = **1133.00**
- ordinary_stack = 105000；LTCG 30000 落在 105000→135000，单身 15% 档(48350<...<533400)全程 15% → **4500.00**
- nii=35000；magi≈100000+35000=135000 < 200000 → NIIT **0.00**
- total = **5633.00**

> 税额例涉及 stacking，末位分对 Decimal 路径敏感。Codex 按 §4 实现后，我会**独立重算并逐分核对**；若与上值有分差，按"修舍入策略"处理，不改黄金值迁就 float。

---

## 5. 设计决策（我已按 IRS 规则拍板，附依据；简化处明确标注）

- **C-1 状态**：脏数据 → `invalid_input`（区别于 `not_covered`）。
- **C-2 持有期**：>1 年为长期，按日历年加法（闰年安全）；黄金不取恰好 1 年边界。依据 IRS Topic 409。
- **C-3 跨 asset 不匹配**：按 asset 分组。✅
- **C-4 netting**：实现 Schedule D 短/长期互抵。
- **C-5 净亏**：不计 $3,000 抵扣/结转，仅报净亏 + assumption 说明（需整表上下文，避免假确定）。
- **C-6 NIIT MAGI**：优先用入参 `modified_agi`；缺省近似为 `other_taxable_income + 净投资收益`，标 assumption。
- **C-7 范围外（写进 assumptions / 已知限制）**：洗售规则（crypto 现行不适用，仍注明）、specific-ID 之外的指定批次、跨年度结转、真实 Form 8949 PDF 导出、质押/空投/分叉等收入性事件（属普通收入，非本函数）。

---

## 6. 黄金用例清单（供 Codex 落地 + Claude 复核）
`tests/golden/crypto_gain_estimate.json`（扁平 schema，与现有一致）：
- `fifo_match`：数据集 D + FIFO → short_term_gain 5000.00, long_term_gain 30000.00
- `hifo_match`：数据集 D + HIFO → short_term_gain 10000.00, long_term_gain 15000.00
- `lifo_match`：数据集 D + LIFO → short_term_gain 10000.00, long_term_gain 15000.00
- `fifo_tax_single_100k`：上 + other_taxable_income 100000, single → tax_estimate.total 5633.00（st 1133.00 / ltcg 4500.00 / niit 0.00）
- `oversell_invalid`：卖 2.0 但只买 1.5 → status invalid_input, reason 含 "exceeds"
- `bad_method`：method "ABC" → invalid_input
- `net_loss`：构造净亏 → tax_estimate 全 0.00 + assumptions 含结转说明
- `niit_triggered`：大额利得 + other_taxable_income 高于阈值 → niit > 0（具体值实现后我核）

边界单测(test_engine.py)：部分 lot 跨多笔消耗、持有期恰好>1年一天、0 数量拒绝、未知 asset 卖出超卖。

---

## 7. 交付物与分工
- **Codex**：`engine/tax_engine.py` 加 `crypto_gain_estimate` + 必要 helper（日期解析、Decimal 单价）；`rules_loader.py` 加 `load_capital_gains_rules`；`__init__.py` 导出；`tests/golden/crypto_gain_estimate.json`；`tests/test_engine.py` 边界单测。纯函数、只读 JSON、Decimal、复用 `_response`/`_not_covered`、新增 `_invalid_input` 构造器。分支 `feature/step2_2-crypto`，PR 到 main，CI 绿。
- **Claude**：本设计；实现后独立重算匹配三例 + 税额例逐分核对 + 查 stacking/NIIT 逻辑。
- **Shaw**：合并 PR。

## 8. 退出门槛
- [ ] 匹配三例(FIFO/HIFO/LIFO)gains 精确一致；税额例逐分对齐(Decimal)。
- [ ] invalid_input 路径(超卖/坏 method/0 数量)被拦且 reason 清晰。
- [ ] 纯函数、只读 JSON、无裸写税率、复用统一响应。
- [ ] ruff + unittest discover + 数据校验 CI 三卡点绿；两份 index.html hash 不变。
- [ ] Claude review 通过(用 [Blocker]/[Major]/[Minor])。

## 9. 之后：Step 2.3 RSU（MVP）
归属普通收入(qty×FMV)税务影响 + "立即 vs 持有满 1 年转 LTCG"对比，税率全部取自 `us_capital_gains`/`us_federal`，不裸写、不做未来股价投机。
