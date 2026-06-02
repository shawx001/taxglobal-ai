# Step 1.1 设计文档 — 资本利得 / NIIT 数据层（解锁 RSU + Crypto）

日期：2026-06-02
阶段：PLM 阶段 2（Design，数据步）
依据：`docs/engineering_process.md`、Step 1 数据层流程
分支：`feature/step1_1-capital-gains`
角色：本文件由 Claude 编写并已查证 2025 数值；实现/归档交 Codex。

> 目的：补齐 `crypto_gain_estimate` / `rsu_tax_estimate` 所缺的**资本利得税率数据**。没有这一步，那两个函数只能裸写 `0.20` 之类税率，违反"税率必须来自 data/"。本步**只建数据 + 归档来源 + 校验**，不写引擎函数（那是 Step 2.2）。

---

## 1. 已查证的 2025 数值（官方来源）

### 1.1 长期资本利得（LTCG）按 taxable income 分档（Rev. Proc. 2024-40）
税率 0% / 15% / 20%，断点为**应税收入**阈值：

| 申报身份 | 0% 上限 (≤) | 15% 上限 (≤) | 20% |
|---|---|---|---|
| single | 48,350 | 533,400 | 以上 |
| married_filing_jointly | 96,700 | 600,050 | 以上 |
| head_of_household | 64,750 | 566,700 | 以上 |
| married_filing_separately | 48,350 | 300,000 | 以上 |
| qualifying_surviving_spouse | 96,700 | 600,050 | 以上 |

- ✅ single / mfj / hoh 已 web 核实。
- ⚠️ **mfs / qss 待用已归档的 `irs_rp_2024_40` 原文逐字确认**（mfs 习惯为 48,350 / 300,000；qss 同 mfj）。固化前 Codex/Shaw 核一下这两行。

### 1.2 短期资本利得（STCG）
持有 ≤ 1 年 → **按普通所得税率**，不另存税率，引用 `us_federal.json` 的 `ordinary_income_brackets`。来源 IRS Topic 409（持有期定义）。

### 1.3 净投资收益税（NIIT，§1411）
- 税率 **3.8%**；对 **min(净投资收益, MAGI − 阈值)** 征收。
- MAGI 阈值（**法定、不随通胀调整**）：

| 申报身份 | MAGI 阈值 |
|---|---|
| single / head_of_household | 200,000 |
| married_filing_jointly / qualifying_surviving_spouse | 250,000 |
| married_filing_separately | 125,000 |

来源：IRC §1411 / IRS Topic 559 / Form 8960 (2025) 说明。

---

## 2. 要归档的来源

| source_id | 文件 | 用途 | 状态 |
|---|---|---|---|
| `irs_rp_2024_40` | 已在仓库 | LTCG 档位 | ♻️ 复用（无需重抓） |
| `irs_topic_409` | https://www.irs.gov/taxtopics/tc409 | 持有期 / STCG=普通 / 资本利得概览 | 🆕 归档 HTML |
| `irs_topic_559` | https://www.irs.gov/taxtopics/tc559 | NIIT 3.8% + 阈值 | 🆕 归档 HTML |

归档方式同 Step 1：抓页面存 `data/sources/us/2025/raw/`，在 `source_manifest.json` 补条目（source_id/title/url/type/publisher/tax_year/jurisdiction/topics/local_path/content_hash/status=archived）。若抓取 403，按 Step 1 惯例标 `failed_sources` 并在数据里把对应块标 `source_pending`，**不要裸写**。

---

## 3. 新数据文件：`data/tax_years/2025/us_capital_gains.json`

```jsonc
{
  "schema_version": "0.1",
  "rule_version": "us-2025-capital-gains-v0.1",
  "tax_year": 2025,
  "jurisdiction": "US",
  "status": "effective",
  "effective_date": "2025-01-01",
  "source_ids": ["irs_rp_2024_40", "irs_topic_409", "irs_topic_559"],

  "long_term_capital_gains": {
    "citation": "Rev. Proc. 2024-40 sets 2025 maximum 0% and 15% rate taxable-income thresholds for net capital gain.",
    "effective_date": "2025-01-01",
    "source_ids": ["irs_rp_2024_40"],
    "brackets": {
      "single":                      [{"up_to": 48350, "rate": 0.0}, {"up_to": 533400, "rate": 0.15}, {"up_to": null, "rate": 0.20}],
      "married_filing_jointly":      [{"up_to": 96700, "rate": 0.0}, {"up_to": 600050, "rate": 0.15}, {"up_to": null, "rate": 0.20}],
      "qualifying_surviving_spouse": [{"up_to": 96700, "rate": 0.0}, {"up_to": 600050, "rate": 0.15}, {"up_to": null, "rate": 0.20}],
      "head_of_household":           [{"up_to": 64750, "rate": 0.0}, {"up_to": 566700, "rate": 0.15}, {"up_to": null, "rate": 0.20}],
      "married_filing_separately":   [{"up_to": 48350, "rate": 0.0}, {"up_to": 300000, "rate": 0.15}, {"up_to": null, "rate": 0.20}]
    }
  },

  "short_term_capital_gains": {
    "treatment": "ordinary_income",
    "note": "Short-term gains (held <= 1 year) are taxed at ordinary rates; use us_federal.json ordinary_income_brackets.",
    "effective_date": "2025-01-01",
    "source_ids": ["irs_topic_409"]
  },

  "net_investment_income_tax": {
    "rate": 0.038,
    "applies_to": "lesser_of_net_investment_income_or_magi_over_threshold",
    "citation": "IRC 1411 / IRS Topic 559: 3.8% on the lesser of net investment income or MAGI over the filing-status threshold.",
    "effective_date": "2025-01-01",
    "source_ids": ["irs_topic_559"],
    "magi_thresholds": {
      "single": 200000,
      "head_of_household": 200000,
      "married_filing_jointly": 250000,
      "qualifying_surviving_spouse": 250000,
      "married_filing_separately": 125000
    }
  }
}
```

设计要点：
- LTCG 用和 `us_federal.json` 一样的 `{up_to, rate}` 分档结构 → Step 2.2 引擎可复用 `bracket_tax` 思路（但需处理"利得叠在普通收入之上"的 stacking，那是引擎的事）。
- STCG 不存税率，显式声明 `treatment: ordinary_income` 并指回联邦档。
- 不裸写任何税率：全部带 `source_ids` + `citation` + `effective_date`，符合工程底线。

---

## 4. 校验脚本补充（`tests/validate_step1_data.ps1`）

把 `us_capital_gains.json` 纳入现有校验，新增断言：
- 文件存在、合法 JSON、`tax_year==2025`、`status==effective` 必有 `effective_date`。
- 所有 `source_ids` 能在 manifest 解析（含新归档的 409/559）；不得用 deprecated `sources` 键。
- `long_term_capital_gains.brackets` 必须含全部 5 种申报身份，每条最后一档 `up_to==null`。
- `net_investment_income_tax.magi_thresholds` 必须含全部 5 种申报身份；`rate==0.038`。

---

## 5. 交付物与分工
- **Codex（数据/代码）**：归档 Topic 409 + 559；补 `source_manifest.json`；建 `us_capital_gains.json`（照 §3）；扩 `validate_step1_data.ps1`（照 §4）。分支 `feature/step1_1-capital-gains`，PR 到 main。
- **Claude（本文件 + review）**：已查证数值；实现后我核对 §1 数值、来源是否官方、校验是否真生效。
- **Shaw**：确认 §1.1 的 mfs/qss 两行（拿已归档 Rev. Proc. 原文）。

## 6. 退出门槛
- [ ] Topic 409 / 559 已归档且 manifest hash 校验通过。
- [ ] `us_capital_gains.json` 合法、5 身份齐全、全部带来源。
- [ ] mfs/qss LTCG 断点经原文确认。
- [ ] 数据校验脚本通过；不引入引擎/前端改动。
- [ ] 两份 index.html hash 不变。

## 7. 之后（Step 2.2，单列）
数据到位后实现 `crypto_gain_estimate`（逐笔 HIFO/FIFO/LIFO 成本基匹配 → 分长短期 → 用本数据估税 + NIIT）与 `rsu_tax_estimate`（归属普通收入 + 行权-持有 LTCG 对比），各自黄金测试。原型里的 `mult:0.55` / 裸写 `0.20` 是 demo 假数，不得搬入。
