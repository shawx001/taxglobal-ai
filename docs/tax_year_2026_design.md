# Step A 设计文档 — 2026 税年数据集(税年升级)

日期：2026-06-03
阶段：PLM 阶段 2（Design）/ M2 前置（口径升级）
依据：现有 `data/tax_years/2025/` 结构、`engine/rules_loader.py`、`income_tax_summary`；官方 2026 源见 §5。
分支：`feature/tax-year-2026`（基于 #24 合并后的 main）
角色：Claude 出设计 + **逐项核验官方 2026 数源** + 重算已验证黄金值；Codex 实现数据/默认切换/测试；Shaw 拍板合并。
工程标准：数值精确第一——每个数附官方出处；2026 与 2025 同构，仅替换通胀调整值 + OBBBA 结构变化。

> 目标：新增 `data/tax_years/2026/`（联邦/FICA/资本利得/QBI/FEIE/州 占位）并把**引擎默认税年切到 2026**，同时保留 2025 数据用于补/改 2025 申报。所有依赖默认税年的黄金值会变 → 本步重算并锁定 2026 版。

---

## 0. 范围
- 新增 `data/tax_years/2026/`：`us_federal.json` / `us_fica.json` / `us_capital_gains.json` / `us_qbi.json` / `us_feie.json`（+ `us_states.json` / `us_nexus.json` 见下）。结构与 2025 完全一致,只换数值。
- **引擎默认税年 → 2026**（`income_tax_summary(..., tax_year=2026)` 等签名默认值）。
- **2025 数据保留**（不删）：补/改 2025 税年仍可用 `tax_year=2025`。
- **州数据(`us_states.json`)**：本步先把 2026 联邦+FICA+资本利得+QBI+FEIE 做实;州 2026 参数多数州尚未发最终手册(截至 2026-06-03),故 2026 州数据**沿用 2025 州表并在每州标 `state_parameter_year:2025`**(诚实标注,与你调研同口径),州 2026 更新与扩州(NJ/OR/PA + WA 资本利得税)放 **Step B**。

## 1. 已核验的 2026 联邦参数(逐项对官方源,见 §5)
### 标准扣除(§63；Rev. Proc. 2025-32）
single 16,100 / married_filing_jointly 32,200 / married_filing_separately 16,100 / head_of_household 24,150。

### 普通所得税档（up_to 上限, 税率 10/12/22/24/32/35/37%）
- single：12,400 / 50,400 / 105,700 / 201,775 / 256,225 / 640,600 / ∞
- married_filing_jointly：24,800 / 100,800 / 211,400 / 403,550 / 512,450 / 768,700 / ∞
- married_filing_separately：12,400 / 50,400 / 105,700 / 201,775 / 256,225 / 384,350 / ∞ （IRC §1(j)：各档=MFJ÷2，逐档验证为精确半值）
- head_of_household：17,700 / 67,450 / 105,700 / 201,775 / 256,200 / 640,600 / ∞

### 长期资本利得/合格股息断点（0% 上限 / 15% 上限；其上 20%）
- single：49,450 / 545,500
- married_filing_jointly：98,900 / 613,700
- married_filing_separately：49,450 / 306,850 （=MFJ÷2）
- head_of_household：66,200 / 579,600

### NIIT（§1411，法定不随通胀）
rate 3.8%；MAGI 门槛 single 200,000 / mfj 250,000 / mfs 125,000 / hoh 200,000。

### FICA / SE（2026）
- Social Security wage_base **184,500**（SSA 2026，↑8,400）；employee_rate 6.2%；self_employment_combined_rate 12.4%。
- Medicare employee_rate 1.45%；self_employment_combined_rate 2.9%（无上限）。
- Additional Medicare 0.9%；门槛 single 200,000 / mfj 250,000 / mfs 125,000 / hoh 200,000（法定不变）。
- SE：net_earnings_multiplier 0.9235（法定不变）。

### FEIE（§911）
maximum_exclusion **132,900**；physical_presence_days 330（法定不变）。

### QBI（§199A）
rate 20%；threshold（应税收入起点 → phase-in 终点）：
- single / head_of_household / qualifying_surviving_spouse：201,750 → 276,750
- married_filing_separately：201,775 → 276,775（Rev. Proc. 2025-32 / IRB 2025-45 §4.26 将 MFS 单列一行,与 All Other Returns 不同）
- married_filing_jointly：403,500 → 553,500
- **结构变化(OBBBA)**：phase-in 区间由 $50k/$100k **扩大到 $75k/$150k**（单/联）。`us_qbi.json` 的 phase-in 范围字段需相应更新。

## 2. 2026 关键变化（OBBBA, One Big Beautiful Bill Act）
1. **TCJA 税率结构永久化**：37% 顶档不再日落；7 档结构延续。
2. **底两档额外通胀调整**（10%/12% 档 +4%，其余 +2.3%，平均约 +2.7%）——已体现在上面档位数值。
3. **§199A QBI phase-in 区间扩大到 $75k/$150k**（影响引擎 QBI 限制相位计算）。
4. 标准扣除、FEIE、SS 基数按 2026 上调（见 §1）。
> 与本引擎计算范围无关的 OBBBA 条款（小费/加班扣除、SALT、老人附加扣除、QBI $400 最低扣除等）本步不建模;命中再标 assumptions / 列后续 REQ。

## 3. 默认税年切换 + 测试策略（关键）
把默认从 2025 改成 2026 会让"不传 tax_year"的旧测试按 2026 算而失败。对策：
- **现有 2025 单测 / golden 全部显式钉 `tax_year=2025`**（它们本就是在验 2025 规则,应当钉年）——含 `tests/test_engine.py`、`tests/golden/income_tax_summary.json`、`tests/test_api_calc.py`、`tests/test_integration_income_summary.py`（后者已钉 2025 ✓）。
- **新增 2026 golden**（默认路径,不传 tax_year）锁定 2026 数值(见 §4)。
- 前端总览发 `tax_year` 由 2025 改 2026 放 **Step C**;本步只动引擎/数据/测试。

## 4. 2026 黄金值(实现后由 Claude 用 2026 数据逐分重算并锁定)
重算下列场景的 2026 版（替代 2025 的 60465.20 等），写入新 golden：
- A 工资 200k + 长期利得 50k, single
- B 海外 200k / 330 天, single
- C 自雇 60k + 长期 40k + 海外 100k / 330 天, single（验 QBI phase-in 新区间 + net_capital_gain 修复仍在）
- D 自雇 100k + CA（CA 仍用 2025 州表,标 `state_parameter_year:2025`）
（数值待 2026 数据落地后由参考实现逐分产出;Codex 先按公式实现,Claude 核验。）

## 5. 数源（archival / source_ids）
- **Rev. Proc. 2025-32**（IRS 2026 通胀调整,含 OBBBA 修订）→ source_id `irs_rp_2025_32`。https://www.irs.gov/pub/irs-drop/rp-25-32.pdf
- IRS Newsroom：2026 inflation adjustments（标准扣除/FEIE/AMT 官方表述）。
- **SSA 2026**：Social Security wage base 184,500（2025-10-24 公告）→ source_id `ssa_press_2026`。
- Tax Foundation 2026 brackets（各身份档位 + LTCG 交叉核对）。
- MFS 档位/LTCG：IRC §1(j) 法定=MFJ÷2（逐档精确验证）；MFS QBI 阈值=非联合(=single) per §199A(e)(2)。

## 6. 验收门槛
- [ ] `data/tax_years/2026/` 五个规则文件齐,结构同 2025,每个数值对得上 §1 + 官方源;`rule_version` 标 2026 + `irs_rp_2025_32`。
- [ ] 引擎默认 `tax_year=2026`;`tax_year=2025` 仍逐分复现旧值(回归)。
- [ ] 现有 2025 测试全部钉 `tax_year=2025` 后通过;新增 2026 golden(A–D)逐分对齐(Claude 重算)。
- [ ] QBI phase-in 用新 $75k/$150k 区间(单测覆盖一个落在 phase-in 内的高收入 SE+资本利得 case)。
- [ ] ruff + unittest + 数据校验 + `git diff --check` 全绿;两份 index.html hash 不变(本步不动前端)。
- [ ] Claude 逐项核验 2026 每个数 vs 官方源 + 逐分重算 A–D。

## 7. 交付物与分工
- **Codex**：`data/tax_years/2026/*.json`（按 §1 数值;2026 州表暂复制 2025 并标 `state_parameter_year:2025`）;`engine` 默认 tax_year→2026;现有 2025 测试钉年;新增 2026 golden + QBI phase-in 单测;交付记录 `docs/tax_year_2026.md`;更新 `feature_status.md`/`product_backlog.md`。分支 `feature/tax-year-2026`,PR→main,CI 绿。
- **Claude**：本设计 + 数源核验;实现后逐项核数 + 逐分重算 A–D + 回归 2025。
- **Shaw**：拍板、合并。

## 8. 之后
Step B：2026 州表更新 + 扩 NJ/OR/PA + WA 资本利得税接进 `income_tax_summary` 州路径。
Step C：前端总览改发 `tax_year=2026` + 加「RSU(本年归属)」独立桶 + golden/清单同步 2026。
