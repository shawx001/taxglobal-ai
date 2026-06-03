# Step 2.6 设计文档 — 加密资本利得「州税」(REQ-012,5 所得税州 + WA excise,务必算准)

日期：2026-06-02
阶段：PLM 阶段 2（Design，含数据 + 引擎）
依据：Step 2.2 `crypto_gain_estimate`、Step 1.4 各州 `tax_base`、REQ-012;州级资本利得税调研(见 §1,附官方源)
分支：`feature/step2_6-crypto-state-tax`(基于 main)
角色：Claude 出设计 + 已查证黄金值;Codex 实现、开 PR、合并;Shaw 拍板。
范围决定(Shaw)：**5 个所得税州 + WA excise 一起做**;前端展示留作下一小块(§8)。

> 目标:给加密**净资本利得**算**州税**,精确到分。**5 个所得税州(CA/NY/GA/IL/CO)把资本利得当普通收入征**——复用 Step 1.4 `tax_base` + `state_income_tax`(增量法)。**WA 是独立的资本利得 excise(7%/超百万 9.9%、仅长期、超标准扣除才征)**——新数据 + 单独算法。无所得税州=0;未覆盖州=诚实 not_covered。

---

## 1. 调研结论(决定怎么算,附官方/权威源)
1. **5 个所得税州全部把资本利得当普通收入征,无优惠率**(Tax Foundation / 多源核实):CA(最高 13.3%)、NY(10.9%)、GA(5.19% flat)、IL(4.95% flat)、CO(4.40% flat)。→ 加密净利得**当普通收入加进州税基**,按州率算。
2. **短期 vs 长期在这 5 州无区别**(都按普通收入)→ 州税对**净利得合计 = net_short + net_long** 计(均取正部分;净亏见 §5)。
3. **CO 的 5 年期资本利得减免**只适用科罗拉多境内不动产/有形资产,**对加密(无形)不适用** → CO 全额 4.40%。
4. **WA = 资本利得 excise**(RCW 82.87,WA DOR):**7%** 税率,**仅长期资本资产**(持有>1年);超 **标准扣除**(2025 待坐实)才征;**超 $1,000,000 部分再 +2.9%(合计 9.9%)**,2025 追溯生效(SB 5813)。**法律上是 excise 不是所得税**(WA 无个人所得税)。crypto 短期利得 **不进 WA excise → $0**。
5. 无个人所得税且无 excise 的州(FL/NV/TX 等)→ 加密利得州税 **0**;`source_pending`(MA/TX)/未知州 → **not_covered** 诚实标注。

> ⚠️ **WA 标准扣除数值有冲突**:WA DOR 官方页显示 **2025 = $278,000**,部分二手源写 $270,000。"算准"原则:**数据步以归档的 WA DOR 官方特别通知为准**(建议取 $278,000,落地时对归档源逐字确认;此值直接改结果,见 §4)。**$1M 档是按"扣除后"还是"扣除前"计**——需对 WA 法条/DOR 特别通知确认(本设计 §3 暂按"扣除后净 WA 利得"计,标为待确认)。

## 2. 数据改动(`data/tax_years/2025/us_states.json` + 归档源)
- **5 所得税州**:各 `tax_base` 加 `"capital_gains_treatment": "ordinary_income"`(显式、可审计;引擎据此把利得当普通收入,**不裸写"所有州都这样"**;将来有资本利得减免/优惠的州可填别的值)。
- **WA**:加 `capital_gains_excise` 块:
```jsonc
"WA": { ... 现 income_tax_type:"none" ...,
  "capital_gains_excise": {
    "rate": 0.07,
    "surtax_rate": 0.029, "surtax_threshold": 1000000,   // 超 $1M 部分 +2.9% = 9.9%
    "standard_deduction": 278000,                          // ⚠️ 对归档 WA DOR 官方数逐字确认(278000 vs 270000)
    "long_term_only": true,
    "citation": "Washington DOR capital gains tax (RCW 82.87); 7% on long-term gains above the annual standard deduction; additional 2.9% on the portion over $1,000,000 effective 2025 (SB 5813).",
    "source_ids": ["wa_dor_capital_gains_2025"],
    "notes": "Excise tax, not income tax. Real estate, retirement accounts, and certain business assets are exempt (not applicable to crypto). Residency/sourcing assumed in-state. $1M tier base (pre/post standard deduction) to be confirmed against the WA DOR special notice."
  } }
```
- **归档**:把 WA DOR 资本利得页/特别通知存入 `data/sources/us/2025/raw/`(raw 字节)+ `source_manifest.json`(hash)。
- **校验** `validate_step1_data.ps1`:有 `capital_gains_excise` 的州必须含 rate/standard_deduction(数值)/long_term_only(bool);`capital_gains_treatment` ∈ {ordinary_income}(目前)。

## 3. 引擎(`engine/tax_engine.py`)
新增纯 helper(Decimal,复用现有 `_state_taxable_base` + `state_income_tax` + `_bracket_tax_decimal`):
```
_crypto_state_tax(state_code, *, net_short_term_gain, net_long_term_gain,
                  other_state_income, filing, tax_year) -> dict:
  block = load_state_rules(tax_year)["states"].get(state_code.upper())
  if not block: return {status:"not_covered", tax:0.00, reason:...}
  # WA 式 excise:
  if block.get("capital_gains_excise"):
      cge = block["capital_gains_excise"]
      lt = max(0, net_long_term_gain)                      # 仅长期;短期不计
      base = max(0, lt - cge["standard_deduction"])
      tax = min(base, cge["surtax_threshold"]) * cge["rate"] \
            + max(0, base - cge["surtax_threshold"]) * (cge["rate"] + cge["surtax_rate"])
      return {status:"ok", type:"excise", tax:_money, rate:cge["rate"], note:"long-term only"}
  status = block.get("status"); itype = block.get("income_tax_type")
  if status != "effective": return {status:"not_covered", tax:0.00, reason:...}
  if itype == "none": return {status:"ok", type:"no_state_income_tax", tax:0.00}
  if itype in {"flat","progressive"} and block.get("tax_base",{}).get("capital_gains_treatment")=="ordinary_income":
      gain = max(0, net_short_term_gain) + max(0, net_long_term_gain)   # 当普通收入
      # 增量法(累进州也准;平税州自然=gain×flat):
      base_wo = _state_taxable_base(block, federal_agi=other, federal_taxable_income=other, ... )
      base_w  = _state_taxable_base(block, federal_agi=other+gain, federal_taxable_income=other+gain, ...)
      tax = state_income_tax(code, base_w, filing).tax - state_income_tax(code, base_wo, filing).tax
      return {status:"ok", type:"ordinary_income", tax:_money(max(0,tax))}
  return {status:"not_covered", tax:0.00, reason:...}
```
集成进 `crypto_gain_estimate`:加入参 `state_code: str | None = None`(**复用现有 `other_taxable_income` 作为州叠加基数**,口径近似,标 assumption);当 `state_code` 提供时:
- `result` 加 `state` 块(`{state, type, tax, status, reason?}`)。
- `result` 加 `total_tax_including_state = tax_estimate.total + state.tax`(联邦 total 字段**保持不变=联邦**,避免破坏现有黄金/测试)。
- `citations` 合并州源;`assumptions` 加州税口径/边界。
> **不改 `state_income_tax` 签名;不改联邦 `tax_estimate.total` 语义**(现有 53 测试不动)。`state_code=None` 时行为与现状完全一致。

## 4. 黄金用例(已用现有 state 机器逐分核;Codex 实现后我再独立重算)
**净利得 35000(数据集 D FIFO:ST 5000 + LT 30000),`other_taxable_income`=100000,single:**
| 州 | state.tax | 校验 |
|---|---|---|
| CA | **3255.00** | 35000×9.3% 边际 |
| NY | **2100.00** | ×6% |
| GA | **1816.50** | =35000×5.19%(flat) |
| IL | **1732.50** | =35000×4.95% |
| CO | **1540.00** | =35000×4.40% |
| FL/NV | **0.00** | 无所得税 |
| MA | **not_covered** | source_pending |
| WA | **0.00** | LT 30000 < 标准扣除 |

**WA excise(仅长期,std=278000 待坐实):** LT 500000 → `(500000−278000)×7%` = **15540.00**;LT 1500000 → `(1000000)×7% + (1500000−278000−1000000)×9.9%`... = **91978.00**(若 std 改 270000 → 16100 / 92770;**此差异即为何要坐实官方数**)。短期 50 万、长期 0 → WA **0.00**。

## 5. 诚实边界(写进 assumptions)
- **其它收入近似**:州叠加基数用 `other_taxable_income`(应税收入)近似州 AGI 基数,与 `income_tax_summary` 同口径;累进州(CA/NY)若用户其它收入口径不同会有小偏差。建议前端尽量传准。
- **WA**:标准扣除取归档官方数(278000 待逐字确认);$1M 档基数(扣除前/后)待对 WA 特别通知确认;假设 WA 居民、crypto 不属豁免类资产。
- **CO** 5 年期资本利得减免对加密不适用(已据此全额)。
- 有资本利得**部分减免/优惠**的州(如 AR/ND/NM/SC/WI 等)**不在本期覆盖的 5 州内**;将来扩州时按各州 `capital_gains_treatment` 数据处理,不静默套用普通收入。
- 净资本亏损:州税 0(沿用联邦净亏处理 + 结转说明)。

## 6. 验收(退出门槛)
- [ ] 5 州增量州税逐分对齐(CA 3255 / NY 2100 / GA 1816.50 / IL 1732.50 / CO 1540);WA excise(LT 50万=15540@std278k、LT 30000=0、短期=0)逐分对齐。
- [ ] **现有 crypto 联邦黄金不变**(`tax_estimate.total` FIFO@10万 仍 5633、`state_code=None` 行为不变,53 测试通过)。
- [ ] WA `standard_deduction`/`$1M 档基数` 已对归档 WA DOR 官方源逐字确认;归档 + manifest hash + 校验通过。
- [ ] 纯函数、Decimal、复用引擎、不裸写税率(州率/扣除全来自 `us_states.json`);不改 `state_income_tax` 签名、不改联邦 total 语义。
- [ ] ruff + unittest + 数据校验 + pip-audit + `git diff --check` 全绿;两份 index.html hash 不变(本步不碰前端)。
- [ ] Claude **逐行** review + 独立重算 + WA 官方数核验。

## 7. 交付物与分工
- **Codex**:`us_states.json`(5 州加 `capital_gains_treatment`;WA 加 `capital_gains_excise`)+ 归档 WA DOR 源 + manifest;`engine/tax_engine.py` 加 `_crypto_state_tax` + 给 `crypto_gain_estimate` 加 `state_code` 与 `state`/`total_tax_including_state`;`tests/golden/crypto_gain_estimate.json` 加带州用例;`tests/test_engine.py` 边界(WA 短期=0、WA 超百万分档、not_covered 州、flat=gain×rate);`validate_step1_data.ps1` 扩;`product_backlog.md` REQ-012 → 🟡/进行中;设计(本文件)+ 交付记录。分支 `feature/step2_6-crypto-state-tax`,PR→main,CI 绿。
- **Claude**:本设计 + 已查证黄金值;实现后逐行 review + 逐分重算 + WA 官方数核验 + 确认联邦 total 未被破坏。
- **Shaw**:坐实 WA 标准扣除官方数(或我用归档源确认)、拍板、合并。

## 8. 之后(下一小块)
前端:crypto 模块加 `cr-state` 选择器 + 展示 `state` 税额(联邦 + NIIT + 州 = 总),WA 标注"仅长期 excise";把现有"仅联邦不含州税"横幅在选了覆盖州后替换为含州税的完整结果。REQ-009(全收入合并计税)把 SE/W2/crypto/海外并进一处仍为更后续。
