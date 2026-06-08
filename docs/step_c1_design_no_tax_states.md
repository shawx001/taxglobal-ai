# Step C1 设计文档 — 无税州(AK, NH, SD, TN, WY) + 激活 TX

日期：2026-06-08
批次：C1（50 州覆盖第一批）
引擎改动：**零**——纯数据 + 测试

## 1. 目标

将 6 个无个人所得税州加入 `us_states.json`（2025 & 2026），状态设为 `effective`：

| 州 | 全名 | 说明 | 官方依据 |
|---|---|---|---|
| AK | Alaska | 从未征收个人所得税 | Alaska DOR: Alaska does not have a personal income tax or a state sales tax |
| NH | New Hampshire | 2025 起完全无所得税（I&D 税 2024 年底废除） | NH DRA RSA 77:1-a — Interest & Dividends Tax repealed effective 2025-01-01 per HB 2 (2023) |
| SD | South Dakota | 从未征收个人所得税 | SD DOR: South Dakota does not have an individual income tax |
| TN | Tennessee | Hall Tax 2021 起废除 | TN DOR: Hall Tax fully repealed effective 2021 (Public Chapter 3, 2016) |
| WY | Wyoming | 从未征收个人所得税 | WY DOR: Wyoming does not have an individual income tax |
| TX | Texas | 州宪法禁止所得税 | TX Comptroller: Texas has no state income tax (Art. VIII §24-a, TX Constitution) |

## 2. 数据模型

每州条目完全匹配已有 FL/NV 模式：

```json
{
  "name": "<Full State Name>",
  "income_tax_type": "none",
  "status": "effective",
  "effective_date": "2025-01-01",
  "flat_rate": 0,
  "source_ids": ["<state_source_id>"],
  "citation": "<one-sentence official citation>",
  "state_parameter_year": 2025
}
```

关键字段：
- `income_tax_type: "none"` → 引擎走 flat/none 分支，`rate=0`，`tax=0`
- `flat_rate: 0` → 保持一致性（FL/NV 都有此字段）
- 不设 `tax_base`——无税州不需要
- `state_parameter_year: 2025` → 参数基于 2025 年确认

## 3. NH 特别说明

New Hampshire 历史上征收 Interest & Dividends (I&D) Tax，税率 5%（2023 年降至 3%，2024 年降至 2%）。
根据 HB 2 (2023 session)，该税种于 **2025-01-01** 完全废除。
因此对于 tax_year >= 2025，NH 是真正的零所得税州。
`notes` 字段注明此历史背景。

## 4. TX 激活

TX 已在 2025/2026 JSON 中存在，状态为 `source_pending`。
激活步骤：
1. 改 `status` → `"effective"`
2. 加 `effective_date: "2025-01-01"`
3. 加 `flat_rate: 0`
4. 加 `source_ids` 引用新的 source manifest 条目
5. 加 `citation`
6. 删 `notes`（pending 说明不再需要）

## 5. Source Manifest

在 `data/sources/us/2025/source_manifest.json` 的 `sources` 数组中添加 6 个条目。
由于这些是官方州税务局通用页面（非特定 PDF），使用 `status: "not_archived"` + `notes` 说明来源。

```
source_id: ak_dor_no_income_tax
source_id: nh_dra_interest_dividends_repeal
source_id: sd_dor_no_income_tax
source_id: tn_dor_hall_tax_repeal
source_id: wy_dor_no_income_tax
source_id: tx_comptroller_no_income_tax
```

## 6. 测试

### 6.1 Golden 值（state_income_tax.json）
每州 1 个 case（100k single），验证 `status: "ok", rate: 0, tax: 0.00`：
- `ak_zero`, `nh_zero`, `sd_zero`, `tn_zero`, `wy_zero`
- `tx_zero`（替换现有 `tx_blocked` case）

### 6.2 单元测试（test_engine.py）
已有 FL/NV/WA zero case 覆盖 `income_tax_type: "none"` 分支。
新 golden 值自动通过 `test_state_income_tax_golden` 验证。
TX 从 `not_covered` → `ok`——需更新任何引用 TX blocked 的断言。

### 6.3 数据验证（validate_step1_data.ps1）
- 新增 spot-check 断言：TX `income_tax_type` == "none" && `status` == "effective"
- 2026 同理

### 6.4 Summary-level 回归
income_tax_summary 2026 golden 不涉及这 6 州——回归安全。

## 7. 不变项
- `engine/state.py` — 零改动
- `engine/summary.py` — 零改动
- `frontend/index.html` — 不动（frontend 州列表更新为后续独立任务）
- `index.html`（根） — 不动

## 8. 验收标准
- [ ] 6 州在 2025 & 2026 JSON 中 `status: "effective"`
- [ ] `source_ids` 全部在 manifest 中存在
- [ ] `state_income_tax("AK", 100000)` → `{status: "ok", tax: 0}`
- [ ] `state_income_tax("TX", 100000)` → `{status: "ok", tax: 0}`（不再 not_covered）
- [ ] `python -m unittest discover -s tests` 全绿
- [ ] `ruff check engine backend tests` 无 error
- [ ] `validate_step1_data.ps1` 全通过
