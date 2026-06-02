# Step 2.3 设计文档 — rsu_tax_estimate（RSU 归属税务 + 持有对比，MVP）

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：`engineering_process.md`、`coding_standards.md`、`us_federal.json`、`us_capital_gains.json`
分支：`feature/step2_3-rsu`
角色：Claude 出设计 + 查证；Codex 实现。本步是"算税大脑"最后一个引擎函数。

> 范围（已确认 MVP）：归属普通收入税务影响 +「立即卖 vs 持有满 1 年转 LTCG」的对比。**不投机未来股价**——未来/实际卖出价由调用方作为输入传入，引擎只算，不猜。原型里裸写的 `(futureValue-opt)*0.20` 不得搬入。

---

## 1. 函数契约

```
rsu_tax_estimate(
    shares_vested: float,
    fair_market_value_per_share: float,    # 归属当日 FMV，= 每股普通收入，也是 §83 成本基
    vest_date: str,                        # ISO YYYY-MM-DD
    filing_status: str = "single",
    other_taxable_income: float = 0.0,     # 用于把 RSU 普通收入叠到正确税档
    sale_scenario: dict | None = None,     # 可选 {"sale_date": ISO, "sale_price_per_share": float}
    tax_year: int = 2025,
) -> dict
```
`result`：
```
{
  "vesting": {
    "shares": <float>,
    "fmv_per_share": <float>,
    "ordinary_income": <shares * fmv>,           # §83 归属普通收入
    "cost_basis_per_share": <fmv>,               # 已按普通收入计税的基
    "vest_income_tax": <叠加后的增量普通所得税>
  },
  "hold_vs_sell": null | {                        # 仅当传入 sale_scenario
    "sale_date": ..., "sale_price_per_share": ...,
    "capital_gain": <(sale_price - fmv) * shares>,
    "term": "long" | "short",
    "capital_gains_tax": <长期=LTCG stacking / 短期=普通增量>,
    "note": "卖在归属日资本利得≈0；持有满1年后增值按LTCG，通常低于短期普通税率。"
  }
}
```
状态：`ok` / `invalid_input`（负股数、FMV<0、日期非法、sale_date < vest_date 等）。`rule_version` 用 federal + capital_gains 组合；citations 取两者来源。

---

## 2. 算法

1. `ordinary_income = shares × fmv`（归属即普通收入，§83）。
2. `vest_income_tax = bracket_tax(other_taxable_income + ordinary_income) − bracket_tax(other_taxable_income)`（用 `us_federal` 普通档，Decimal）。
3. `cost_basis_per_share = fmv`（已计普通收入，避免重复征税）。
4. 若有 `sale_scenario`：
   - `capital_gain = (sale_price_per_share − fmv) × shares`（可负=亏）。
   - 持有期：`sale_date > vest_date + 1 年` → `long`，否则 `short`（与 crypto 同一规则）。
   - 税：
     - 长期 → 用 LTCG stacking，落在 `ordinary_stack = other_taxable_income + ordinary_income` 之上（**复用 crypto 的 `_long_term_capital_gains_tax`**）。
     - 短期 → 普通增量：`bracket_tax(ordinary_stack + gain) − bracket_tax(ordinary_stack)`。
     - 亏损 → `capital_gains_tax = 0` + assumption 注明本函数不算 $3,000 抵扣/结转。
5. 全程 Decimal；展示字段 `_money` 量化。

> DRY：**复用 Step 2.2 已有的** `_bracket_tax_decimal` / `_long_term_capital_gains_tax` / 日期解析 / `_invalid_input`，不要复制粘贴新写一套。

---

## 3. 设计决策（已拍板，附依据）

- **R-1 FICA 不在本函数算**：RSU 归属同时是 W-2 工资,需缴社保/医保/附加医保。但那应通过 `fica_tax`(把归属价值并入 wages)处理,本函数只算**所得税 + 资本利得**,保持单一职责。**用 assumption 明确写出**"归属价值还需计 FICA,见 fica_tax"。依据 IRC §83 + 工资性质。
- **R-2 不投机未来股价**：`sale_scenario` 由调用方传入(实际或假设的卖出价/日期),引擎不内置增长率预测。符合"不给假确定性"。
- **R-3 成本基 = 归属 FMV**(§83),持有后只对**增值部分**算资本利得,杜绝重复征税。
- **R-4 复用资本利得机制**：持有卖出就是一笔资本利得,和 crypto 共用 stacking/分档逻辑。

范围外(写进 assumptions/已知限制)：ISO/ESPP/NQSO 等其他股权形式、83(b) 选择、预扣不足补缴、AMT、多批 vest 的逐批(本步先单次 vest;多批可后续扩 list 输入)。

---

## 4. 黄金用例（期望值已手算，single，2025）

设定：1000 股归属 @ FMV $50，`other_taxable_income` 150000，vest_date 2024-03-01。
- `ordinary_income` = **50000.00**
- `vest_income_tax` = bracket(200000) − bracket(150000) = 41063.00 − 28847.00 = **12216.00**

| 用例 | sale_scenario | 期望 |
|---|---|---|
| `vest_only` | 无 | ordinary_income 50000.00, vest_income_tax 12216.00, hold_vs_sell null |
| `hold_long` | 2025-06-01 @ $80（>1年，长期） | capital_gain 30000.00, term long, capital_gains_tax **4500.00**（30000×15%，stack 在 200000 之上全 15% 档） |
| `sell_short` | 2024-09-01 @ $80（~6月，短期） | capital_gain 30000.00, term short, capital_gains_tax **9600.00**（bracket(230000)−bracket(200000)，主要 32% 档） |
| `invalid_neg_shares` | shares -10 | status invalid_input |
| `invalid_sale_before_vest` | sale_date < vest_date | status invalid_input |

对比含义：同样 $30,000 增值，持有满 1 年(LTCG) **4500** vs 短期(普通) **9600**，持有省 **5100**——这是真实数据驱动的结论，非原型的假 0.20。

边界单测：持有恰好 1 年→short；卖出价<FMV→负 capital_gain 且 capital_gains_tax 0 + 结转 assumption。

---

## 5. 交付物与分工
- **Codex**：`engine/tax_engine.py` 加 `rsu_tax_estimate`(复用现有资本利得/bracket helper);`__init__` 导出;`tests/golden/rsu_tax_estimate.json`;`tests/test_engine.py` 边界单测;`docs/step2_3_design_rsu.md` 一并提交;交付记录 `docs/step2_3_rsu_engine.md`。纯函数、只读 JSON、Decimal、无裸写税率、复用 `_response`/`_invalid_input`。分支 `feature/step2_3-rsu`,PR 到 main,CI 绿。
- **Claude**：本设计;实现后独立重算 vest_income_tax 与长/短期对比逐分核对。
- **Shaw**：合并 PR。

## 6. 退出门槛
- [ ] vest_only / hold_long / sell_short 三例逐分一致;invalid_input 被拦。
- [ ] 复用而非复制资本利得逻辑(DRY)。
- [ ] 纯函数、只读 JSON、无裸写税率、FICA 用 assumption 标注。
- [ ] ruff + unittest discover + 数据校验 CI 三卡点绿;两份 index.html hash 不变。
- [ ] Claude review 通过([Blocker]/[Major]/[Minor])。

> 本步合并后,引擎层 9 个函数(bracket/federal/fica/SE/feie/state/nexus/crypto/rsu)齐备,"算税大脑"完成,进 Step 4 FastAPI 把它服务化。
