# Step 3 / M3 设计文档 — 黄金测试集（Golden Tests）

日期：2026-06-02
阶段：PLM 阶段 2（Design + Test Case Review）
依据：`docs/engineering_process.md`、`docs/phase1_define_us_mvp.md`、Step 2 引擎
分支：`feature/step3-golden-tests`
角色：本文件由 Claude（评审方）编写，供 Shaw 评审；实现交 Codex。

> 阶段 2 只产出"怎么做"与"测什么"，不写实现代码。本文件给出**精确的期望值基线**，Codex 据此落地 `tests/golden/*.json` 与运行器；之后由 Claude 对照本基线 review。

---

## 1. 目标与范围

把 Step 2 已验证的引擎行为**固化为回归基线**，防止后续改动悄悄改坏税额或拒绝逻辑。

> 范围修订（2026-06-02）：原稿以"函数还没写"为由排除 SE/nexus/RSU/crypto，**判据错误**。正确判据是**数据层支不支持**。修订如下。

### In Scope（数据已齐全 → 本轮固化）
- 原 5 个：`bracket_tax` / `federal_income_tax` / `fica_tax` / `feie_estimate` / `state_income_tax`
- 新增 2 个（先经 Step 2.1 实现，见 `docs/step2_1_design_se_nexus.md`）：`self_employment_tax`（数据在 `us_fica.json`）、`nexus_estimate`（数据在 `us_nexus.json`）
- 即 **M3 黄金集覆盖 7 个函数**，含全部拒绝路径。

### Out of Scope（数据层缺失 → 补数据后再做，非"不能做"）
`rsu_tax_estimate` / `crypto_gain_estimate` 依赖**资本利得税率（LTCG/STCG/NIIT）**，该数据 `data/` 里尚不存在。现在硬写就得裸写税率，违反"税务数字必须来自 data/"。故按已确认顺序：先 Step 1.1 补 `us_capital_gains.json`（IRS 官方来源），再 Step 2.2 实现并补黄金测试。CA/NY 累进州税同理（`pending_extraction`），本步只固化其"拒绝计算"行为。

### 设计原则
- **不只测 happy path**：每个函数必须含 成功 + 边界 + 拒绝 三类。
- **拒绝路径是一等公民**：CA/NY/MA/TX/unknown 必须固化为 `not_covered`，防止有人给 pending 州填了值忘改状态。
- **数据驱动**：用例写在 `tests/golden/*.json`，运行器统一加载断言，新增用例不改代码。
- **可追溯**：每条用例固化 `rule_version` 与 `citation source_ids`，呼应"每个结论可追溯"的底线。

---

## 2. 黄金用例文件 Schema

`tests/golden/<function>.json`：

```jsonc
{
  "function": "federal_income_tax",
  "cases": [
    {
      "name": "single_w2_120k",
      "purpose": "W-2 普通收入，single，标准扣除",   // 必填：场景目的
      "args": { "gross_income": 120000, "filing_status": "single" },
      "expect": {
        "status": "ok",
        "result": { "taxable_income": 105000.00, "tax": 18047.00 },  // 子集匹配
        "rule_version": "us-2025-federal-v0.1",
        "citation_source_ids": ["irs_rp_2024_40"],   // 子集，顺序不敏感
        "assumptions_nonempty": true,
        "reason": null
      }
    }
  ]
}
```

拒绝类用例：
```jsonc
{
  "name": "state_ca_blocked",
  "purpose": "CA pending_extraction 必须拒绝计算",
  "args": { "state_code": "CA", "taxable_income": 100000 },
  "expect": {
    "status": "not_covered",
    "result": null,
    "reason_contains": "pending_extraction",
    "rule_version": "us-2025-states-v0.1"
  }
}
```

---

## 3. 运行器规格（`tests/test_golden.py`）

- 加载 `tests/golden/*.json`，按 `function` 字段 dispatch 到对应引擎函数。
- 用 `subTest(name=...)` 逐用例断言，失败信息须带 `name`，一眼看出哪个税务模块变了。
- **比较语义（精确指定，避免歧义）**：
  - 金额字段：用 `==` 比较（引擎已 `_money` 量化到 2 位，确定性，不需要容差）。
  - `result`：**子集匹配**——`expect.result` 里出现的 key 必须相等；引擎多返回的 key 不算失败。
  - `result: null` → 断言引擎返回 `result is None`。
  - `citation_source_ids`：断言为引擎返回 `citations[*].source_id` 的**子集**，顺序不敏感。
  - `assumptions_nonempty: true` → `len(assumptions) > 0`。
  - `reason_contains`：子串匹配；`reason: null` → 断言 `reason is None`。
- `bracket_tax` 用例的 `args` 直接带 `brackets` 数组（该函数不读 JSON）。

---

## 4. 黄金用例清单（Test Case Review — 期望值已由 Claude 独立计算）

> 下列数值我已手算并与 Step 2 引擎实跑核对一致，**除 GA 外**（见 §7）。Codex 直接采用，不要再"猜"。

### 4.1 `bracket_tax`（brackets = [10k@10%, 20k@20%, ∞@30%]）
| name | 输入 | 期望 tax |
|---|---|---|
| below_first_cap | 5000 | 500.00 |
| at_first_cap | 10000 | 1000.00 |
| mid_second | 15000 | 2000.00 |
| at_second_cap | 20000 | 3000.00 |
| into_top | 25000 | 4500.00 |
| zero | 0 | 0.00 |
| negative_clamped | -100 | 0.00 |

### 4.2 `federal_income_tax`（2025，标准扣除：single 15000 / mfj 30000 / hoh 22500）
| name | args | taxable | tax | rule_version |
|---|---|---|---|---|
| single_w2_120k | 120000, single | 105000.00 | 18047.00 | us-2025-federal-v0.1 |
| single_50k | 50000, single | 35000.00 | 3961.50 | 〃 |
| single_at_std_ded | 15000, single | 0.00 | 0.00 | 〃 |
| single_below_std_ded | 10000, single | 0.00 | 0.00 | 〃 |
| single_top_bracket_700k | 700000, single | 685000.00 | 210470.25 | 〃 |
| mfj_120k | 120000, mfj | 90000.00 | 10323.00 | 〃 |
| hoh_120k | 120000, hoh | 97500.00 | 14625.00 | 〃 |
| single_itemized_override | 120000, single, deduction=30000 | 90000.00 | 14714.00 | 〃 |

citation_source_ids 全部 = `["irs_rp_2024_40"]`；assumptions_nonempty=true。`mfj`/`hoh` 经 alias 归一化后 `input.filing_status` 应为全称。

### 4.3 `fica_tax`（2025，SS .062/base 176100，Medicare .0145，Addl .009）
| name | args | SS | Medicare | Addl | total |
|---|---|---|---|---|---|
| single_100k_below_cap | 100000, single | 6200.00 | 1450.00 | 0.00 | 7650.00 |
| single_at_addl_threshold | 200000, single | 10918.20 | 2900.00 | 0.00 | 13818.20 |
| single_250k | 250000, single | 10918.20 | 3625.00 | 450.00 | 14993.20 |
| single_300k_ss_capped | 300000, single | 10918.20 | 4350.00 | 900.00 | 16168.20 |
| mfj_250k_no_addl | 250000, mfj | 10918.20 | 3625.00 | 0.00 | 14543.20 |
| mfs_200k | 200000, mfs | 10918.20 | 2900.00 | 675.00 | 14493.20 |

要点固化：①SS 在 176100 封顶（300k 与 200k/250k 的 SS 都是 10918.20）；②附加医保按申报身份阈值（single 200k / mfj 250k / mfs 125k）；③200000 single 恰在阈值 → Addl=0（验证"恰好等于阈值不触发"）。

### 4.4 `feie_estimate`（2025，max 130000，330 天）
| name | args | qualifies | excluded | remaining |
|---|---|---|---|---|
| pass_at_330_over_cap | 140000, 330 | true | 130000.00 | 10000.00 |
| fail_at_329 | 140000, 329 | false | 0.00 | 140000.00 |
| pass_under_cap | 100000, 330 | true | 100000.00 | 0.00 |
| pass_at_cap | 130000, 365 | true | 130000.00 | 0.00 |

### 4.5 `state_income_tax`（2025）
成功类：
| name | args | status | rate | tax | citation |
|---|---|---|---|---|---|
| fl_zero | FL, 100000 | ok | 0 | 0.00 | fl_personal_income_tax_faq |
| nv_zero | NV, 100000 | ok | 0 | 0.00 | nv_tax_notes_194 |
| wa_zero | WA, 100000 | ok | 0 | 0.00 | wa_income_tax |
| il_flat | IL, 100000 | ok | 0.0495 | 4950.00 | il_2025_individual_income_tax_whats_new |
| co_flat | CO, 100000 | ok | 0.044 | 4400.00 | co_individual_income_tax_guide |
| **ga_flat** ⚠️ | GA, 100000 | ok | 0.0519 | **5190.00（待核对，见 §7）** | ga_2025_it511_booklet |
| il_zero_income | IL, 0 | ok | 0.0495 | 0.00 | 〃 |
| il_negative_clamped | IL, -100 | ok | 0.0495 | 0.00 | 〃 |

拒绝类（全部 status=not_covered，result=null，rule_version=us-2025-states-v0.1）：
| name | args | reason_contains |
|---|---|---|
| ca_blocked | CA, 100000 | pending_extraction |
| ny_blocked | NY, 100000 | pending_extraction |
| ma_blocked | MA, 100000 | source_pending |
| tx_blocked | TX, 100000 | source_pending |
| unknown_blocked | ZZ, 100000 | not present |

### 4.6 `self_employment_tax` / 4.7 `nexus_estimate`
期望值见 `docs/step2_1_design_se_nexus.md` §4（避免重复维护）。要点：SE 走 Decimal 路径逐分对齐；nexus 固化 NY 双条件语义（`ny_sales_over_tx_under` 不得触发），WA/未知州走 not_covered。这两组随 Step 2.1 实现后并入同一个 `tests/test_golden.py` 运行器与同一份 CI。

---

## 5. CI 设计（`.github/workflows/ci.yml`）

触发：`push` 到 `main` + 所有 `pull_request`。单 job（ubuntu-latest，Python 3.11）：

| 步骤 | 命令 | 卡点性质 |
|---|---|---|
| checkout / setup-python | actions/checkout@v4 + setup-python@v5 | — |
| 安装工具 | `pip install ruff pip-audit` | — |
| Lint | `ruff check engine tests` | **阻塞** |
| 依赖安全扫描 | `pip-audit`（暂非阻塞，加 `|| true`） | 非阻塞* |
| 单测 + 黄金测试 | `python -m unittest discover -s tests -v` | **阻塞** |
| 数据层校验 | `pwsh tests/validate_step1_data.ps1` | **阻塞** |

\* pip-audit 当前无第三方依赖可审，先非阻塞接上占位；等 Step 4 出 `requirements.txt` 后改 `pip-audit -r requirements.txt` 并转阻塞。

补充：
- 新增 `ruff.toml`：`line-length = 120`、`target-version = "py311"`、默认启用 `E,F,I`（含 import 排序）。引擎代码很小且干净，若有零星告警让 Codex 直接修复，不要无脑 `# noqa`。
- `validate_step1_data.ps1` 用 `Get-FileHash/Test-Path/ConvertFrom-Json`，在 GitHub ubuntu 自带的 `pwsh` 下跨平台可跑；脚本 `throw` 会以非零退出，CI 能捕获。

---

## 6. 交付物与分工

**Codex 实现（代码）：**
- `tests/golden/bracket_tax.json`、`federal_income_tax.json`、`fica_tax.json`、`feie_estimate.json`、`state_income_tax.json`（照 §4 期望值）
- `tests/golden/self_employment_tax.json`、`nexus_estimate.json`（照 `step2_1_design_se_nexus.md` §4；随 Step 2.1 实现后落地）
- `tests/test_golden.py`（照 §3 运行器规格）
- `ruff.toml`
- `.github/workflows/ci.yml`（照 §5）

**Claude 实现（文档/评审）：**
- 本设计文档（已交付）
- 实现后对照 §4 基线逐值 review + 本地独立重算抽查 + 确认 CI 真的跑了全部卡点（不是绿但空跑）

**Shaw：**
- §7 GA 复核；确认 `feature/step3-golden-tests` 开分支、PR 合并。

---

## 7. 风险与待办（必须在固化前处理）

- ✅ **GA 5.19% 已核实（2026-06-02）**：Georgia HB 111（2025-04-15 签署）将个税降为 **5.19% 平税，追溯至 2025-01-01，适用全年 2025 收入**。`flat_rate: 0.0519` 与黄金值 5190.00 正确，可直接固化。
  - 排雷记录：官方 DOR "Important Tax Updates" 页当前（2026-06）首屏显示的是 **2026 年的 4.99%**，易误读；2025 实为 5.19%，已用 HB 111 + 多个薪酬/税务来源交叉确认。
- ✅ **CO 4.40% 已核实**：2025 年 TABOR 临时降率（→4.25%）**未触发**（超额收入 $293.3M < $300M 门槛），故 2025 维持 **4.40%**。`flat_rate: 0.044` 与黄金值 4400.00 正确。
- 其余州费率（IL/FL/NV/WA）与全部联邦/FICA/FEIE 值此前已独立核对，可直接固化。

## 8. M3 退出门槛（Exit Criteria）

- [ ] §4 全部用例落地为 `tests/golden/*.json` 且期望值与本文件一致（GA 以核对结果为准）。
- [ ] `tests/test_golden.py` 跑通，成功 + 边界 + 拒绝三类均覆盖。
- [ ] CI 在 PR 上跑：ruff / unittest / 数据层校验 三个阻塞卡点全绿。
- [ ] `index.html` 与 `frontend/index.html` 仍 hash 一致（未触前端）。
- [ ] Claude 对照 §4 review 通过；PR 合并入 `main`。
