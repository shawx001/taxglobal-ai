# Step B2 设计文档 — 扩州 NJ + PA(gross-income 税基)

日期：2026-06-03
阶段：PLM 阶段 2（Design）/ Step B 扩州(第 2 子步)
依据：`engine/state.py` `_state_taxable_base`、`engine/summary.py` 州路径;官方 NJ Division of Taxation / PA DOR(见 §5)。
分支：`feature/step-b2-nj-pa`(基于最新 main)
角色：Claude 出设计 + 已验证单身黄金值 + 数源核验;Codex 实现;Shaw 拍板。
工程标准：**数据驱动**(新州=改数据 + 通用 `start_from` 分支,无州名特判);数值精确到分;诚实标注未建模项。

> 目标:加 **NJ(gross income tax,累进)** 和 **PA(flat 3.07%)** 两个所得税州。二者共享一个新的 **`start_from:"gross_income"`** 税基(= 税前总收入,州不认联邦线上扣除)。**OR 拆到 Step B2b**——它的"联邦税减项 + AGI 退坡"依赖联邦税额 + 一张退坡表,需单独查准做对,硬塞进来会逼出不准近似。

---

## 0. 为什么需要新税基 `gross_income`
现有 `_state_taxable_base` 只支持 `start_from` = `federal_agi` / `federal_taxable_income`(± 标准扣除/免税额/QBI 加回)。NJ/PA **不以联邦 AGI/应税收入为起点**:
- **NJ**:gross income tax——按 NJ 毛收入计,**不允许联邦扣除**(含线上扣除),仅给 **$1,000 个人免税额(单/户;已婚联合 $2,000)**;资本利得并入毛收入按 NJ 累进档计(无优惠率)。
- **PA**:flat 3.07%,**无标准扣除/免税额**,按 PA 应税收入(毛收入口径)计。
→ 需要新 `start_from:"gross_income"`,其值 = **税前总收入** = W-2 + 自雇净利润 + 其它普通收入 + 短/长期利得 + 海外收入(按 FEIE 前金额,再扣州 tax_base 数据声明的免税额/扣除)。

## 1. 引擎改动(数据驱动扩展)
1. `engine/summary.py`:计算 `gross_income` 为 FEIE 前、联邦线上扣除前的收入桶合计,在调 `_state_taxable_base(...)` 时多传 `gross_income=gross_income`。
2. `engine/state.py` `_state_taxable_base`:新增形参 `gross_income: Decimal` + 新分支:
   ```
   if start_from == "gross_income":
       if tax_base.get("no_tax_gross_income_threshold") and gross_income <= threshold[filing]:
           return 0
       base = gross_income
       if tax_base.get("exemption_per_person"):           # NJ：$1,000/人，无退坡
           count = 2 if filing == "married_filing_jointly" else 1
           base -= exemption_per_person * count
       elif tax_base.get("standard_deduction"):           # 预留
           base -= standard_deduction[filing]
       return max(0, base)                                 # PA：无扣除，base=gross
   ```
   **不写州名特判**;NJ/PA 行为完全由各自 tax_base 数据驱动。
3. 不改联邦/FICA/QBI/FEIE/其它州;`income_tax_type` 沿用现有 `progressive`(NJ)/`flat`(PA)路径。

## 2. 数据(`data/tax_years/2025/` 与 `2026/` 的 `us_states.json`,均标 `state_parameter_year:2025`)
**NJ**(`income_tax_type:"progressive"`,`tax_base:{start_from:"gross_income", no_tax_gross_income_threshold:{single/MFS:10000, MFJ/HOH/QSS:20000}, exemption_per_person:1000, capital_gains_treatment:"ordinary_income"}`):
- 单身/已婚分别(NJ Rate Schedule I)brackets(up_to, rate):20000@.014 / 35000@.0175 / 40000@.035 / 75000@.05525 / 500000@.0637 / 1000000@.0897 / null@.1075。**已验证(单身)。**
- **已婚联合/户主/QSS(NJ Rate Schedule II)**:Codex 按官方 NJ Division of Taxation Rate Schedules 录入(含 2.45% 档),Claude 逐分核。
**PA**(`income_tax_type:"flat"`,`flat_rate:0.0307`,`tax_base:{start_from:"gross_income", capital_gains_treatment:"ordinary_income"}`):全档统一 3.07%。

## 3. 已验证黄金值(单身,2026 联邦 + 州 2025 口径;Claude 独立逐分核)
- **NJ — W-2 150,000, single**:联邦 24,734.00 / 工资税 11,475.00 / **NJ 州税 7,365.05** / **total 43,574.05**。
- **PA — W-2 150,000, single**:联邦 24,734.00 / 工资税 11,475.00 / **PA 州税 4,605.00** / **total 40,814.00**。
- **混合(NJ)**:W-2 100,000 + 长期利得 50,000, single → NJ 对利得按普通档计(gross 150,000−1,000=149,000,州税同上 7,365.05;联邦侧 LTCG 优惠另算)——验"资本利得并入 NJ 毛收入按普通率"。
（其余 filing status 的州税由 Codex 录入后 Claude 逐分核。）

## 4. 诚实边界(写进 assumptions / notes)
- NJ:养老金/退休收入排除、NJ 专项减项与抵免、NJ medical 等未建模;`gross_income` 用"联邦线上扣除前总收入"近似 NJ 毛收入(NJ 对 401(k) 等的口径与联邦不同,属简化)。
- PA:PA 八类所得的分类损失规则、PA 专项扣除未建模;按总收入 × 3.07% 近似。
- 两州均按"州居民、全部为州内来源"假设;非居民/来源分配未建模。

## 5. 数源
- **NJ**:NJ Division of Taxation — Tax Rate Schedules / Tax Tables(`nj.gov/treasury/taxation/taxtables.shtml`);$1,000 个人免税额、Rate Schedule I/II。source_id 如 `nj_dor_tax_rate_schedules_2025`。
- **PA**:PA Department of Revenue — 个人所得税 flat 3.07%。source_id 如 `pa_dor_pit_rate`。

## 6. 验收门槛
- [ ] NJ/PA 单身黄金值逐分命中(NJ 7,365.05 / total 43,574.05;PA 4,605.00 / total 40,814.00);混合 NJ 利得按普通档。
- [ ] `gross_income` 分支数据驱动,无州名特判;非 NJ/PA 州 + 联邦行为完全不变(回归)。
- [ ] NJ 各 filing status brackets 对齐官方 Rate Schedule(Claude 逐分核)。
- [ ] ruff + unittest + 数据校验 + `git diff --check` 全绿;两份 index.html hash 不变(本步不动前端)。
- [ ] 2025 + 2026 两年 us_states.json 都加 NJ/PA,标 `state_parameter_year:2025`。

## 7. 交付物与分工
- **Codex**:`engine/summary.py`(传 gross_income)+ `engine/state.py`(gross_income 分支);`data/tax_years/{2025,2026}/us_states.json` 加 NJ/PA(全 filing status,带 source_ids);golden 加 NJ/PA 单身 + 混合;`test_engine` 边界(gross_income 分支、NJ 免税额、PA flat、回归非 gross 州);交付记录 `docs/step_b2_nj_pa.md`;更新 `feature_status.md`/`product_backlog.md`/`roadmap_skills_status.md`。分支 `feature/step-b2-nj-pa`,PR→main,CI 绿。
- **Claude**:本设计 + 已验证黄金值;实现后逐分重算 + 官方源核 NJ 各档 + 回归 + 数据驱动核查。
- **Shaw**:拍板、合并。

## 8. 之后
Step B2b：OR(progressive + OR 标准扣除 $2,835 + **联邦税减项上限 $8,500 含 AGI 退坡**)——需把联邦税额传入州税基 + 录入退坡表;单独查准。
