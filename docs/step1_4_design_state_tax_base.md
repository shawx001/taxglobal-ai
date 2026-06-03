# Step 1.4 设计文档 — 州税基规则(让州税精确,不再估算)

日期：2026-06-02
阶段：PLM 阶段 2（Design，数据步）
依据：Step 1.2 州费率、`income_tax_summary`(REQ-011)、各州官方
分支：`feature/step1_4-state-tax-base`
角色：Claude 出设计 + 已查证 2025 数值;Codex 实现。

> 目标:补齐 5 个有所得税州(CA/NY/IL/CO/GA)的**税基规则**——起点(联邦 AGI 还是联邦应税收入)、州标准扣除/免税额、QBI 一致性——让 `income_tax_summary` 用**每个州真实的税基**算州税,**精确到分,取代"估算"**。只建数据 + 校验,不写引擎(引擎在 Step 2.5 revised 用)。

## 0. 为什么必须做(证据)
net 10万自雇、single、加州:用"联邦应税收入"当州税基 → CA $2,371.90;用**真实 CA 税基**(联邦 AGI − CA 标准扣除 $5,706、不减 QBI)→ **$4,550.96**。**差 $2,179(近一倍)**。计算产品不能接受这种误差。

## 1. 各州真实税基(2025,已查证)
| 州 | 起点 | 标准扣除/免税额 | QBI |
|---|---|---|---|
| **CA** | 联邦 AGI | 标准扣除:single/MFS **$5,706**;MFJ/HOH/QSS **$11,412** | 不认(不减) |
| **NY** | 联邦 AGI | 标准扣除:single/MFS **$8,000**;MFJ/QSS **$16,050**;HOH **$11,200** | 不认(+ NYAGI>$107,650 recapture) |
| **GA** | 联邦 AGI | 标准扣除:single/HOH/QSS/MFS **$12,000**;MFJ **$24,000** | 不认 |
| **IL** | 联邦 AGI | **无标准扣除**;人头免税额 **$2,850/人**(联邦 AGI>$250k 单/$500k MFJ 则取消) | 不适用(起点在 AGI 之上) |
| **CO** | 联邦**应税收入** | 用联邦标准扣除(起点已含) | 不认(**加回 federal QBI**) |

> ✅ CA/NY/GA single·MFJ、IL 免税额、CO 起点+QBI 加回 已 web 核实;⚠️ CA/NY 的 HOH/MFS/QSS 三档与**已归档的 FTB 540 / NY IT-201 原文**逐字确认后固化(惯例值已填,见上)。

## 2. 数据落地:扩展 `data/tax_years/2025/us_states.json`
给 CA/NY/IL/CO/GA 各加一个 `tax_base` 块:
```jsonc
"CA": { ... 现有 brackets ...,
  "tax_base": {
    "start_from": "federal_agi",            // federal_agi | federal_taxable_income
    "allows_qbi": false,                     // 是否允许联邦 QBI 扣除
    "standard_deduction": { "single":5706,"married_filing_separately":5706,
      "married_filing_jointly":11412,"qualifying_surviving_spouse":11412,"head_of_household":11412 },
    "citation": "California FTB 2025 Form 540 standard deduction; CA does not conform to IRC 199A (QBI add-back on Schedule CA).",
    "source_ids": ["ca_2025_540_tax_rate_schedules"],
    "notes": "State-specific Schedule CA adjustments, age/blind extra amounts, and credits are not modeled."
  }
}
"NY": { ..., "tax_base": { "start_from":"federal_agi","allows_qbi":false,
    "standard_deduction": {"single":8000,"married_filing_separately":8000,
      "married_filing_jointly":16050,"qualifying_surviving_spouse":16050,"head_of_household":11200},
    "notes":"Tax benefit recapture above $107,650 NYAGI not modeled; NY modifications/credits not modeled." } }
"GA": { ..., "tax_base": { "start_from":"federal_agi","allows_qbi":false,
    "standard_deduction": {"single":12000,"married_filing_separately":12000,
      "married_filing_jointly":24000,"qualifying_surviving_spouse":12000,"head_of_household":12000},
    "notes":"GA retirement income exclusion (62+/65+) and credits not modeled." } }
"IL": { ..., "tax_base": { "start_from":"federal_agi","allows_qbi":false,
    "uses_exemption_allowance": true, "exemption_allowance_per_person": 2850,
    "exemption_phaseout_agi": {"married_filing_jointly":500000,"single":250000,"head_of_household":250000,
      "married_filing_separately":250000,"qualifying_surviving_spouse":250000},
    "notes":"IL subtractions (e.g., federally-taxed retirement income) and additions not modeled; exemption count assumed by filing status." } }
"CO": { ..., "tax_base": { "start_from":"federal_taxable_income","allows_qbi":false,
    "qbi_addback": true,
    "notes":"CO starts from federal taxable income and adds back the federal QBI deduction; CO subtractions/additions not modeled." } }
```
（零税州 TX/FL/WA/NV 无需 tax_base。)

## 3. `income_tax_summary`(Step 2.5)如何用它算精确州税
本数据步只建数据;Step 2.5 revised 的州税分支:
```
若州 income_tax_type==progressive/flat 且有 tax_base:
  start = tax_base.start_from
  if start == "federal_agi":
      state_base = federal_AGI
      − (standard_deduction[filing] 若有;否则 exemption_allowance_per_person×exemption_count 若 AGI≤phaseout)
      （allows_qbi=false → 不减 QBI;federal_agi 起点本就不含 QBI)
  if start == "federal_taxable_income":
      state_base = federal_taxable_income + (federal QBI 若 qbi_addback else 0)
  state_tax = flat_rate×state_base  或  bracket_tax(state_base, brackets[filing])
```
→ **CA/NY/GA/IL/CO 各按真实税基,精确到分**(替代旧"联邦应税收入"估算)。

## 4. 校验脚本补充
- 有 `tax_base` 的州:`start_from` ∈ {federal_agi, federal_taxable_income};若 federal_agi 起点,必须有 `standard_deduction`(5 身份)或 `uses_exemption_allowance`;`allows_qbi` 为布尔;CO 必须 `start_from==federal_taxable_income` 且 `qbi_addback==true`。
- 零税/pending 州不得有 tax_base(或允许但被引擎忽略)。

## 5. 诚实边界(精确到什么程度)
- **精确**:常见自雇/工薪 + 标准扣除的情形,各州 = 真实税基(起点 + 州标准扣除/免税额 + QBI 一致性)→ 算到分。
- **明确标注未建模**(不静默给错数):各州特有的加减项(IL 退休收入减项、GA 退休 exclusion、CA Schedule CA、CO 加减)、年龄/盲人额外扣除、州级抵免、NY recapture。命中这些情形时,引擎应在 assumptions 标注"该州存在未建模的特定调整"。

## 6. 交付物与分工
- **Codex**:扩 `us_states.json`(CA/NY/IL/CO/GA 各加 tax_base,数值照 §1/§2);扩 `validate_step1_data.ps1`(照 §4);设计文档一并提交。分支 `feature/step1_4-state-tax-base`,PR 到 main,CI 绿。**本步不改引擎**(引擎在 Step 2.5 revised)。
- **Claude**:本设计 + 已查证数值;实现后核对(尤其 CA/NY 的 HOH/MFS/QSS 对已归档 FTB 540 / NY IT-201 原文)+ 校验真生效。
- **Shaw**:确认 CA/NY 非 single/MFJ 三档;合并 PR。

## 7. 退出门槛
- [ ] 5 州 tax_base 齐全、数值=§1、结构自洽(CO=federal_taxable+addback;IL=exemption;其余=federal_agi+std)。
- [ ] CA/NY HOH/MFS/QSS 经官方原文确认。
- [ ] 校验通过;无引擎/前端改动;根 index.html hash 未变。
- [ ] Claude review 通过。

## 8. 之后
**Step 2.5(revised)** `income_tax_summary` 用 tax_base 算精确州税(CA net10万 single → CA $4,550.96 而非估算 $2,371.90);黄金用例改为精确值。→ Step 5.4 自雇前端展示**联邦+SE+州全精确**的总税。REQ-011 标记为"核心税基已精确,残余州级调整后续"。
