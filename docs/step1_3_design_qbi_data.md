# Step 1.3 设计文档 — QBI 合格经营收入扣除数据(§199A)

日期：2026-06-02
阶段：PLM 阶段 2（Design，数据步）
依据：`engineering_process.md`、Step 1 数据流程、`tax_rules_self_employment.md`(REQ-008)
分支：`feature/step1_3-qbi-data`
角色：Claude 出设计 + 已查证 2025 数值;Codex 实现。

> 目标:建立 §199A QBI 扣除的 2025 数据层,为后续 `qbi_deduction` 引擎(Step 2.4)和"自雇/经营者数值正确"铺路。**只建数据 + 归档来源 + 校验**,不写引擎。

---

## 1. 已查证的 2025 数值

- **扣除率**:20%(QBI 的 20%,且不超过 "应税收入 − 净资本利得" 的 20%)
- **应税收入阈值(taxable income threshold)**:
  - single / head_of_household / qualifying_surviving_spouse / married_filing_separately:**$197,300**
  - married_filing_jointly:**$394,600**
- **phase-in 窗口(超过阈值后的过渡区间)**:single 等 **$50,000**;MFJ **$100,000**
- **上限(阈值 + 窗口,过了它完全适用限制)**:single 等 **$247,300**;MFJ **$494,600**
- ✅ single / MFJ 已 web 核实(Rev. Proc. 2024-40)。
- ⚠️ **MFS / QSS / HOH 的确切阈值待用已归档的 `irs_rp_2024_40` 原文逐字确认**(惯例:MFS=MFJ 的一半=$197,300、窗口 $50,000;HOH/QSS 通常用 single 阈值;固化前核对)。

> §199A 已由 OBBBA(2025-07)永久化;2025 税年按上述阈值适用。

## 2. 要归档的来源
| source_id | 文件 | 状态 |
|---|---|---|
| `irs_rp_2024_40` | 已在仓库 | ♻️ 复用(QBI 阈值出处) |
| `irs_qbi_deduction` | https://www.irs.gov/newsroom/qualified-business-income-deduction | 🆕 归档 HTML(QBI 概览/规则) |
若抓取 403,按惯例进 `failed_sources` 并标 source_pending,不裸写。

## 3. 新数据文件 `data/tax_years/2025/us_qbi.json`
```jsonc
{
  "schema_version": "0.1",
  "rule_version": "us-2025-qbi-v0.1",
  "tax_year": 2025,
  "jurisdiction": "US",
  "status": "effective",
  "effective_date": "2025-01-01",
  "source_ids": ["irs_rp_2024_40", "irs_qbi_deduction"],
  "qbi_deduction": {
    "rate": 0.20,
    "citation": "IRC 199A: up to 20% of qualified business income; Rev. Proc. 2024-40 sets 2025 taxable-income thresholds.",
    "taxable_income_threshold": {
      "single": 197300, "head_of_household": 197300,
      "married_filing_separately": 197300, "qualifying_surviving_spouse": 197300,
      "married_filing_jointly": 394600
    },
    "phase_in_window": {
      "single": 50000, "head_of_household": 50000,
      "married_filing_separately": 50000, "qualifying_surviving_spouse": 50000,
      "married_filing_jointly": 100000
    },
    "upper_limit": {
      "single": 247300, "head_of_household": 247300,
      "married_filing_separately": 247300, "qualifying_surviving_spouse": 247300,
      "married_filing_jointly": 494600
    },
    "notes": "Below threshold: deduction = min(20%*QBI, 20%*(taxable_income - net_capital_gain)), no wage/SSTB test. Above the upper limit: W-2 wage/UBIA limits apply and SSTB phases out — these require business-specific inputs (W-2 wages, UBIA, SSTB status) and are modeled in a later step."
  }
}
```

## 4. 校验脚本补充(`tests/validate_step1_data.ps1`)
- `us_qbi.json` 纳入:合法 JSON、tax_year 2025、effective 必有 effective_date、source_ids 解析、`rate==0.20`、threshold/window/upper_limit 含全部 5 申报身份;`upper_limit == threshold + phase_in_window`(自洽校验)。

## 5. 关键诚实边界(写进 notes + 后续引擎)
- **阈值以下**:QBI = 20% 精确可算(覆盖多数自雇个人),**数值正确**。
- **阈值以上**:W-2 工资限制 + SSTB(特定服务业)逐步剔除——需要经营体的 W-2 工资、UBIA、是否 SSTB 等输入,**本数据步不解决**,留给 Step 2.4 引擎(届时要么收集这些输入,要么明确标注"高收入段为估算,未完全建模 phase-out")。**不在阈值以上伪装精确。**

## 6. 交付物与分工
- **Codex**:归档 `irs_qbi_deduction`;补 `source_manifest.json`;建 `us_qbi.json`(照 §3,数值精确);扩 `validate_step1_data.ps1`(照 §4)。分支 `feature/step1_3-qbi-data`,PR 到 main,CI 绿。设计文档一并提交。
- **Claude**:本设计 + 已查证数值;实现后核对数值(尤其 MFS/QSS/HOH 对 Rev. Proc. 原文)+ 校验真生效。
- **Shaw**:确认 §1 的 MFS/QSS/HOH 三行;合并 PR。

## 7. 退出门槛
- [ ] `us_qbi.json` 合法、5 身份齐全、rate 0.20、upper_limit=threshold+window 自洽;single/MFJ 数值=§1。
- [ ] MFS/QSS/HOH 经 Rev. Proc. 2024-40 原文确认。
- [ ] 来源归档 + hash 校验;数据校验脚本通过;无引擎/前端改动;根 index.html hash 未变。
- [ ] Claude review 通过。

## 8. 之后
Step 2.4 `qbi_deduction(qbi, taxable_income, filing_status, net_capital_gain=0, ...)`(阈值以下精确;以上按限制/标注)+ 黄金测试 → Step 2.5 `income_tax_summary`(把 净利润→½SE税→QBI→标准扣除→联邦+州+SE税 串成总税)→ Step 5.4 自雇前端展示完整正确总税。
