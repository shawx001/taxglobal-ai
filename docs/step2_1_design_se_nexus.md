# Step 2.1 设计文档 — 补全数据齐全的引擎函数（SE 税 + Nexus）

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：`docs/engineering_process.md`、`docs/step2_tax_engine.md`、`data/tax_years/2025/us_fica.json`、`data/tax_years/2025/us_nexus.json`
分支：`feature/step2_1-se-nexus`
角色：本文件由 Claude（评审方）编写，给出函数契约、算法、数据依赖与待定决策；实现交 Codex。

> 背景：Step 2 只落地了 5 个函数。`self_employment_tax` 与 `nexus_estimate` 的**数据层已齐全**（不需要新数据、不需要裸写税率），所以本步补上；`rsu_tax_estimate` / `crypto_gain_estimate` 依赖尚不存在的资本利得税率数据，留到补数据后（见 §5）。

---

## 1. `self_employment_tax`

### 1.1 数据依赖（全部已在 `us_fica.json`）
- `social_security.self_employment_combined_rate` = 0.124，`social_security.wage_base` = 176100
- `medicare.self_employment_combined_rate` = 0.029
- `additional_medicare.employee_rate` = 0.009，`additional_medicare.taxpayer_thresholds`
- `self_employment.net_earnings_multiplier` = 0.9235
- **无任何新数据、无裸写税率。**

### 1.2 函数契约
```
self_employment_tax(net_self_employment_profit: float,
                    filing_status: str = "single",
                    tax_year: int = 2025) -> dict
```
返回沿用 Step 2 统一结构（status/input/result/breakdown/rule_version/citations/assumptions/reason）。`result`：
```
{
  "net_earnings_from_self_employment": <profit * 0.9235>,
  "social_security_tax": <min(base, 176100) * 0.124>,
  "medicare_tax": <base * 0.029>,
  "self_employment_tax": <ss + medicare>,            // §1401 口径，不含附加医保
  "additional_medicare_tax": <max(0, base - threshold[filing]) * 0.009>,
  "deductible_half_se_tax": <self_employment_tax / 2>, // §164(f)，不含附加医保
  "total_se_related_tax": <self_employment_tax + additional_medicare_tax>
}
```
`rule_version` = `us-2025-fica-v0.1`；`citations` 取 social_security / medicare / additional_medicare / self_employment 的 source_ids。

### 1.3 关键实现要求
- **用 Decimal 做费率乘法**（不要 float 后再 `Decimal(str())`）。0.9235/0.124/0.029 在 float 下会产生半分位漂移（如 230875×0.029 可能落成 6695.3749999），导致末位分不可控。Decimal 路径下结果确定，可与 §4 黄金值逐分对齐。
- 每个展示字段用 `_money`（ROUND_HALF_UP，2 位）；`self_employment_tax`/`deductible_half`/`total` 从**全精度** Decimal 求和后再 round，保证展示字段相加自洽。
- `net_profit <= 0` → base 与所有税额均为 0.00，`status: ok`。

### 1.4 设计决策（已查 IRS 官方核实并拍板，2026-06-02）
- **SE-1 计入 SE 收入上的附加医保税：✅ 是。** IRS 确认 0.9% 附加医保税适用于超阈值的自雇收入（原型 `calcSE` 漏了，计入更准）。
- **SE-2 半额抵扣口径：✅ §164(f)，50% × §1401 SE 税，不含附加医保。** IRS 明确"0.9% 附加医保税不可抵扣；可抵扣的是常规 SE 税的一半"。
- **SE-3 与 W-2 工资协调阈值：MVP 不协调（假设无其他工资），assumptions 写明。** 注：IRS 规则是"先用 Medicare 工资扣减阈值，再对 SE 收入按剩余阈值计算"；待 `income_tax_summary` 合并多收入源时再实现该协调。附加医保阈值比对的是 **SE 净收入（92.35% 基数，即 Schedule SE line 6 / Form 8959 口径）**。
- **SE-4 SE 函数只算 SE 税、不算所得税：✅ 是。** 单一职责；所得税交 `federal_income_tax`/`state_income_tax`。原型把它和 CA 州税混算，而 CA 现为 pending，不能照搬。
- 来源：IRS《Self-employment tax》《Topic 560》《Form 8959 (2025) 说明》《Questions and answers for the Additional Medicare Tax》。

---

## 2. `nexus_estimate`

### 2.1 数据依赖（全部已在 `us_nexus.json`）
- `thresholds.<STATE>.sales_amount` / `.transaction_count` / `.condition` / `.measurement_period` / `.source_ids`
- 覆盖 CA/NY/TX/FL（effective），WA 为 `source_pending`。

### 2.2 函数契约
```
nexus_estimate(state_code: str,
               sales_amount: float,
               transaction_count: int | None = None,
               tax_year: int = 2025) -> dict
```
`result`（status=ok 时）：
```
{
  "state": "CA",
  "threshold": {"sales_amount": 500000, "transaction_count": null, "condition": "amount_only"},
  "inputs": {"sales_amount": <in>, "transaction_count": <in>},
  "exceeded": <bool>,        // 是否已触发经济联结
  "approaching": <bool>,     // 未触发但接近
  "status_label": "triggered" | "approaching" | "below"
}
```
WA（source_pending）/ 未知州 → `status: not_covered`，`result: null`，`reason` 说明（呼应"不给假确定性"）。

### 2.3 触发判定逻辑
- `transaction_count` 为 null 的州（CA/TX/FL）：仅按销售额判定。
- `condition == "amount_and_transactions"` 的州（NY）：**销售额与笔数都超**才算 `exceeded`；缺 `transaction_count` 入参时该轴按"未超"处理（保守），并在 assumptions 注明输入不全。

### 2.4 设计决策（已查官方措辞并拍板，2026-06-02）
- **NX-1 比较运算符：✅ 数据驱动——给 `us_nexus.json` 每条加 `comparison` 字段。** 已核实各州法定措辞确实不同：CA/NY/FL = "exceed / more than" → `gt`；**TX = "$500,000 or more" → `gte`**。运算符由数据承载、引擎按字段判定，不写死。这是一个小幅数据补充（无需新来源，运算符已隐含在现有已归档官方页面里）。补字段前 MVP 统一用 `gt`，并在 assumptions 注明；**黄金测试一律不取恰好等于阈值的输入**，规避边界歧义。
- **NX-2 "approaching" 定义：✅ 默认 `未 exceeded 且 (销售额 ≥ 80% 阈值，或有笔数阈值且笔数 ≥ 80%)`。** 这是产品启发式（非税法红线），实现为命名常量 `NEXUS_APPROACHING_RATIO = 0.80` 便于后续调整。
- **NX-3 多州批量：MVP 单州**；批量在提醒系统（Step 7）按档案逐州调用。
- **WA 备注**：已核实 WA 经济联结真实阈值为 **$100,000**，但官方来源尚未按 Step 1 流程归档，故 `nexus_estimate("WA", ...)` 维持 `not_covered`，直到归档官方页面后再填值（符合"数据是真相源"）。

---

## 3. 统一要求
- 两个函数都是纯函数：只读 JSON、不联网、不读 index.html、不裸写税率。
- 复用 Step 2 的 `_response` / `_not_covered` 构造器，保持 8 键结构一致。
- `engine/__init__.py` 导出新函数。

---

## 4. 黄金用例（期望值，供 Codex 落地 + Claude 复核）

### 4.1 `self_employment_tax`（Decimal 路径，2025，single 附加医保阈值 200000）
| name | net_profit | base | SS | Medicare | SE税(§1401) | 附加医保 | 半额抵扣 | total |
|---|---|---|---|---|---|---|---|---|
| se_100k_single | 100000 | 92350.00 | 11451.40 | 2678.15 | 14129.55 | 0.00 | 7064.78 | 14129.55 |
| se_250k_single | 250000 | 230875.00 | 21836.40 | 6695.38 | 28531.78 | 277.88 | 14265.89 | 28809.65 |
| se_zero | 0 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |

说明：se_250k 同时验证 ①SS 在 176100 封顶（21836.40）②SE 收入 230875 超 200000 触发附加医保 277.88。期望值我用 Decimal 手算；**前提是引擎按 §1.3 走 Decimal**，否则末位分会漂——届时按"修引擎舍入策略"处理，不要改黄金值迁就 float。

### 4.2 `nexus_estimate`（2025，approaching 取 80% 待 NX-2 确认）
成功类（status=ok）：
| name | args | exceeded | approaching | label |
|---|---|---|---|---|
| ca_triggered | CA, 600000 | true | false | triggered |
| ca_approaching | CA, 450000 | false | true | approaching |
| ca_below | CA, 300000 | false | false | below |
| ny_both_triggered | NY, 600000, tx=150 | true | false | triggered |
| ny_sales_over_tx_under | NY, 600000, tx=50 | **false** | true | approaching |
| tx_triggered | TX, 600000 | true | false | triggered |
| fl_triggered | FL, 150000 | true | false | triggered |
| fl_below | FL, 50000 | false | false | below |

`ny_sales_over_tx_under` 是关键用例：销售额超了但笔数没超，AND 条件下**不得**判为已触发——固化 NY 的双条件语义。

拒绝类（status=not_covered，result=null）：
| name | args | reason_contains |
|---|---|---|
| wa_source_pending | WA, 600000 | source_pending |
| unknown_blocked | ZZ, 600000 | not present |

---

## 5. 后续（RSU / crypto，待补数据）
1. **Step 1.1（数据）**：新增 `data/tax_years/2025/us_capital_gains.json`，含 2025 LTCG 0/15/20% 收入档、STCG=普通税率、NIIT 3.8% 及阈值，全部带 IRS 官方 `source_ids`（来源归档同 Step 1 流程）。
2. **Step 2.2（引擎）**：实现 `crypto_gain_estimate`（逐笔 HIFO/FIFO/LIFO 成本基匹配 + 资本利得分类 + 用数据层税率估税）与 `rsu_tax_estimate`（归属普通收入 + 行权-持有 LTCG 对比，税率取自数据层），再各自黄金测试。
3. 原型里的 `mult:0.55/0.78` 与裸写 `0.20` 是 demo 假数,**不得**搬进引擎。

## 6. 退出门槛
- [ ] SE-1..4 / NX-1..2 决策由 Shaw 确认。
- [ ] 两函数实现为纯函数，仅读 JSON，复用统一响应结构。
- [ ] §4 黄金用例落地并通过（SE 走 Decimal，逐分对齐）。
- [ ] Claude 复核：独立重算 SE 三例、核对 nexus 判定逻辑（尤其 NY 双条件）。
