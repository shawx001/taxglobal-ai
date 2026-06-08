# Step B2b 设计文档 — 扩州 OR(俄勒冈:联邦税减项 + 阶梯退坡)

日期：2026-06-03
阶段：PLM 阶段 2（Design）/ Step B 扩州(第 3 子步)
依据：`engine/state.py` `_state_taxable_base`、`engine/summary.py` 州路径;官方 Oregon DOR Pub OR-17 / Form OR-40 instructions / ORS 316.800(见 §5)。
分支：`feature/step-b2b-or`(基于最新 main)
角色：Claude 出设计 + 已验证(低于退坡)黄金值 + 数源核验;Codex 实现 + 录入官方阶梯退坡表;Claude 逐分核。
工程标准：数据驱动(退坡表=数据,引擎通用解释,无州名特判);数值精确到分;诚实标注未建模项。

> 目标:加 **OR(累进)**。难点 = **联邦税减项**:OR 应税基 = 联邦 AGI − OR 标准扣除 − 联邦所得税减项;减项 = `min(联邦所得税额, 上限)`,**上限随 AGI 阶梯退坡**(ORS 316.800 为阶梯式,非线性;2025 通胀调整后:单身上限 \$8,500、AGI \$125k–\$145k 分档降到 0)。引擎需把**联邦税额传入州税基** + 读**阶梯退坡表**。

---

## 0. 已核验的 OR 2025 参数(官方源见 §5)
- **档位(单身)**:4.75%≤\$4,400 / 6.75%≤\$11,050 / 8.75%≤\$125,000 / 9.9% 以上。**已验证(单身)**;MFJ=2× 阈值(8,800 / 22,100 / 250,000),HOH/MFS/QSS 由 Codex 按 OR-40 录入,Claude 核。
- **标准扣除**:single \$2,835(MFJ \$5,710、HOH \$4,565 等由 Codex 按 OR-40 录入并核)。
- **联邦税减项上限**:\$8,500(single/HOH/MFJ/QSS),\$4,250(MFS)。
- **退坡(阶梯,ORS 316.800,2025 通胀值)**:single AGI \$125k–\$145k 间分档降、≥\$145k 为 0;MFJ \$250k–\$290k。**精确的阶梯档(agi_up_to → limit)由 Codex 从 Form OR-40 instructions 的联邦税减项工作表录入,Claude 逐分核**(法条基年表:single <104k→5000/…/≥131k→0,2025 为其通胀调整版)。

## 1. 引擎改动(数据驱动)
1. `engine/summary.py`:计算 **联邦所得税额** `federal_income_tax_liability = federal_income_tax + long_term_capital_gains_tax`(OR 减项基准 = 联邦"所得税",含普通+资本利得税,**不含 NIIT/SE/工资税**);在调 `_state_taxable_base(...)` 时多传 `federal_income_tax=federal_income_tax_liability`。
2. `engine/state.py` `_state_taxable_base`:加形参 `federal_income_tax: Decimal`;在 `start_from=="federal_agi"` 分支支持新配置 `federal_tax_subtraction`:
   ```
   base = federal_agi - standard_deduction[filing]
   if tax_base.get("federal_tax_subtraction"):
       limit = stepped_limit(phaseout_table[filing], federal_agi)   # 走第一个 agi<=agi_up_to 的档的 limit
       subtraction = min(federal_income_tax, limit)
       base -= subtraction
   return max(0, base)
   ```
   **阶梯退坡 = 数据表查找,无州名特判、无硬编码档位。**
3. 不改联邦/FICA/QBI/FEIE/其它州;OR `income_tax_type:"progressive"`。

## 2. 数据(`data/tax_years/{2025,2026}/us_states.json`,标 `state_parameter_year:2025`)
**OR**(`income_tax_type:"progressive"`,`tax_base:{start_from:"federal_agi", allows_qbi:false, capital_gains_treatment:"ordinary_income", standard_deduction:{...}, federal_tax_subtraction:{phaseout_table:{<filing>:[{agi_up_to:..,limit:..},...,{agi_up_to:null,limit:0}]}}}`):
- 档位:single 已验证(见 §0);其余 filing status Codex 按 OR-40 录入。
- 退坡表:Codex 按 Form OR-40 instructions 2025 联邦税减项工作表逐档录入(single/MFJ/MFS/HOH/QSS),Claude 逐分核。

## 3. 已验证黄金值(单身,2026 联邦 + OR 2025;Claude 独立逐分核)
- **OR — W-2 100,000, single(AGI 低于退坡起点,减项满额)**:联邦 13,170.00 / 工资税 7,650.00 / 联邦税额=13,170 → 减项 min(13,170, 8,500)=**8,500** / OR 税基 = 100,000−2,835−8,500=88,665 / **OR 州税 7,449.19** / **total 28,269.19**。
- **退坡区内用例**(如 single AGI 在 \$125k–\$145k):Codex 实现后按录入的阶梯表产出,Claude 对照 OR-40 工作表逐分核。
- **回归**:非 OR 州 + 联邦/NJ/PA/WA/CA 全不变。

## 4. 诚实边界(assumptions / notes)
- OR 联邦税减项基准用 **联邦所得税(普通+资本利得,扣抵免前的近似;不含 NIIT/SE/工资税)** 作 MVP 口径;实际 OR 用"联邦所得税 after credits"——属简化,标注。
- OR kicker(盈余返还抵免)、各类 OR 加项/减项/抵免、居民来源分配未建模。
- 退坡按 OR-40 阶梯表;若年度表未及更新,沿用 2025 并标 `state_parameter_year`。

## 5. 数源
- Oregon DOR **Pub OR-17**(2025)+ **Form OR-40 instructions**(联邦税减项工作表 + 档位 + 标准扣除);**ORS 316.800**(退坡为阶梯式)。source_id 如 `or_dor_pub_or17_2025` / `or_dor_or40_instructions_2025`。

## 6. 验收门槛
- [ ] OR W-2 100k single 逐分命中(州 7,449.19 / total 28,269.19);退坡区用例对齐 OR-40 阶梯表。
- [ ] `federal_tax_subtraction` 数据驱动(阶梯表查找,无州名特判);summary 正确传 `federal_income_tax`(=联邦+LTCG,不含 NIIT/SE)。
- [ ] OR 各 filing status 档位/标准扣除/退坡表对齐官方(Claude 逐分核)。
- [ ] 非 OR 州 + 联邦/NJ/PA/WA 回归不变;ruff + unittest + 数据校验(含 2025+2026 OR + 阶梯表 shape)+ `git diff --check` 全绿;两份 index.html hash 不变。

## 7. 交付物与分工
- **Codex**:`engine/summary.py`(算 federal_income_tax_liability 并传入)+ `engine/state.py`(federal_tax_subtraction + 阶梯退坡查找);`data/tax_years/{2025,2026}/us_states.json` 加 OR(全 filing status 档位/标准扣除/退坡表,带 source_ids + 归档 OR-17/OR-40);golden 加 OR 低于退坡 + 退坡区;`test_engine` 边界(减项满额/退坡分档/≥end 为0/回归);`validate_step1_data.ps1` 加 federal_tax_subtraction shape 校验(并确保 2025+2026 都校验);交付记录 `docs/step_b2b_or.md`;更新 feature_status / product_backlog / roadmap_skills_status / **project.md**。分支 `feature/step-b2b-or`,PR→main,CI 绿。
- **Claude**:本设计 + 已验证黄金值;实现后逐分重算 + 对 OR-40 核档位/退坡表 + 回归 + 数据驱动核查。
- **Shaw**:拍板、合并。

## 8. 之后
Step B 收尾(可选补更多州)→ **M2(LangChain Agent + 18 Skills + GraphRAG)**,先读 `docs/agent_architecture_principles.md`。
