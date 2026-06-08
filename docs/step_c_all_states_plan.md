# Step C 设计规划 — 50 州 + DC 全覆盖

日期：2026-06-08
目标：M1 收尾,把州补全至 51 个税区(50 州 + DC)。
原则：数据驱动,无州名特判;数值精确到分;每批一 PR,CI 绿即 merge。

## 0. 现状(13 已配置,11 effective)

| 模型 | 已做 | 数量 |
|---|---|---|
| none(无税) | FL, NV, WA(excise) | 3 |
| flat | CO, GA, IL, PA | 4 |
| progressive | CA, NJ, NY, OR | 4 |
| source_pending | MA, TX | 2 |
| **合计** | | **13** |

## 1. 还差 38 个,按模型分 5 批

### Step C1: 无税州(6 个)——纯数据,零引擎改动
AK, NH, SD, TN, WY + 激活 TX
→ 全部 `income_tax_type: "none"`,NH 注明 2025 起废除利息/股息税。

### Step C2: 简单 flat 州(10 个 + 激活 MA)——纯数据
| 州 | 税率 | 基 | 备注 |
|---|---|---|---|
| AZ | 2.50% | federal_agi | |
| ID | 5.695% | federal_taxable_income | |
| IN | 3.00% | federal_agi | 2026→2.95% |
| IA | 3.80% | federal_taxable_income | 2025 起 flat |
| KY | 4.00% | federal_agi | |
| LA | 3.00% | federal_agi | 2025 起 flat |
| MI | 4.25% | federal_agi | |
| MS | 4.40% | federal_agi | >$10k 起征(threshold) |
| NC | 4.25% | federal_taxable_income | 2025 降自 4.5% |
| UT | 4.55% | federal_taxable_income | |
| **MA** | 5.00% | federal_agi | **+4% 百万富翁附加税(>$1M)**——需引擎扩展 `surtax` |

→ MA 的 4% surtax 需要引擎支持(新增 `surtax` 配置在 flat_rate 旁)。
→ MS 的 $10k 免税门槛用已有 `no_tax_gross_income_threshold`。

### Step C3: 简单 progressive 州(18 个)——纯数据,federal_agi 基
| 州 | 档数 | 顶率 | 备注 |
|---|---|---|---|
| AR | 2 | 3.90% | |
| DE | 6 | 6.60% | |
| HI | 12 | 11.00% | |
| KS | 2 | 5.58% | |
| ME | 3 | 7.15% | |
| MD | 8 | 5.75% | |
| MO | 7 | 4.70% | |
| MT | 2 | 5.90% | |
| NE | 4 | 5.20% | |
| NM | 6 | 5.90% | |
| ND | 2 | 2.50% | |
| OH | 2 | 3.50% | 无标准扣除,有 exemption phaseout |
| OK | 6 | 4.75% | |
| RI | 3 | 5.99% | |
| SC | 3 | 6.20% | |
| VA | 4 | 5.75% | 很低起点($17k) |
| VT | 4 | 8.75% | |
| WV | 5 | 4.82% | |

### Step C4: 复杂 progressive 州(4 个 + DC)——可能需引擎扩展
| 州 | 档数 | 顶率 | 特殊机制 |
|---|---|---|---|
| AL | 3 | 5.00% | **联邦税减项**(同 OR,已支持) |
| CT | 7 | 6.99% | **税额回收/phaseout**(低档利益高收入回收) |
| DC | 6 | 10.75% | 标准 progressive |
| MN | 4 | 9.85% | **+1% 投资附加税(>$1M)** |
| WI | 4 | 7.65% | 标准扣除 phaseout |

→ AL:用已有 `federal_tax_subtraction`(同 OR),无引擎改动。
→ CT phaseout / MN surtax / WI 标准扣除 phaseout:MVP 可简化——CT 按纯档位、MN/MA surtax 统一引擎扩展、WI phaseout 取全额(标注未建模)。

## 2. 引擎扩展需求(最小化)

| 特性 | 涉及州 | 改动 |
|---|---|---|
| `surtax`(额外税率 on income > threshold) | MA, MN | `state.py` + data schema:flat/progressive 后叠加 `surtax.rate × max(0, base - threshold)` |
| `federal_tax_subtraction` | AL(已有 OR 支持) | 零改动 |
| 标准扣除 phaseout | WI, CT | MVP 取全额,诚实标注;后续按需扩展 |
| `no_tax_threshold`(低于门槛免税) | MS | 已有(NJ 模型) |

**唯一实质引擎改动 = surtax**(~10 行),其余全是数据。

## 3. 批次 & 分支

| 批次 | 分支 | 州数 | 引擎改动 | 预估 |
|---|---|---|---|---|
| C1: 无税 | feature/step-c1-no-tax | 6 | 无 | 轻量 |
| C2: Flat | feature/step-c2-flat | 11 | surtax(MA) | 中 |
| C3a: Progressive(前半) | feature/step-c3a-progressive | 9 | 无 | 中 |
| C3b: Progressive(后半) | feature/step-c3b-progressive | 9 | 无 | 中 |
| C4: 复杂 | feature/step-c4-complex | 5 | AL 数据 + CT/MN/WI notes | 中 |
| **总计** | | **40** | | |

完成后 = 51 个税区全覆盖(50 州 + DC)。

## 4. 验收(每批)
- 新州 golden 值(至少 1 个 per 州,关键州 2 个)
- 回归:已有州不变
- 门禁全绿:unittest + ruff + data validation + diff check
- 每州标 source_ids + 归档官方源(DOR/Tax Foundation)
- project.md 更新州覆盖数

## 5. 之后
51 州 + DC 全覆盖 → deepcopy 性能优化 → M1 正式关闭 → **M2 kickoff**。
