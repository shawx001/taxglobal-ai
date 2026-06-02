# Step 1.2 设计文档 — CA / NY 累进州税(数据 + 引擎 + API + 前端)

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：`engineering_process.md`、`coding_standards.md`、`us_states.json`、Step 2 引擎、Step 4 API、Step 5 前端
分支：`feature/step1_2-ca-ny-state`
角色：Claude 出设计 + 已从官方原文核验数值；Codex 实现。

> 目标：把加州、纽约从 `pending_extraction` 变成可计算的累进州税,端到端打通(数据→引擎→API→前端)。**这不是纯数据步**——`state_income_tax` 需加 `filing_status` 入参 + 累进分支。

---

## 1. 已核验数据(来源:仓库内已归档官方文件)

### 1.1 CA 2025（来源 `ca_2025_540_tax_rate_schedules.pdf`，逐档精确)
`{up_to, rate}`，9 档；Schedule X=single/MFS，Y=MFJ/QSS，Z=HOH：

- **single / married_filing_separately**：11079@1% · 26264@2% · 41452@4% · 57542@6% · 72724@8% · 371479@9.3% · 445771@10.3% · 742953@11.3% · null@12.3%
- **married_filing_jointly / qualifying_surviving_spouse**：22158@1% · 52528@2% · 82904@4% · 115084@6% · 145448@8% · 742958@9.3% · 891542@10.3% · 1485906@11.3% · null@12.3%
- **head_of_household**：22173@1% · 52530@2% · 67716@4% · 83805@6% · 98990@8% · 505208@9.3% · 606251@10.3% · 1010417@11.3% · null@12.3%

> 现有 `bracket_tax` 能精确还原 CA 表(CA 是连续累进;已用官方示例验证:MFJ 应税 $125,000 → $4,768.10）。

### 1.2 NY 2025（来源 `ny_2025_it201_instructions.html`，阈值已 grep 核对)
`{up_to, rate}`，9 档；single/MFS 一表，MFJ/QSS 一表，HOH 一表：

- **single / married_filing_separately**：8500@4% · 11700@4.5% · 13900@5.25% · 80650@5.5% · 215400@6% · 1077550@6.85% · 5000000@9.65% · 25000000@10.3% · null@10.9%
- **married_filing_jointly / qualifying_surviving_spouse**：17150@4% · 23600@4.5% · 27900@5.25% · 161550@5.5% · 323200@6% · 2155350@6.85% · 5000000@9.65% · 25000000@10.3% · null@10.9%
- **head_of_household**：12800@4% · 17650@4.5% · 20900@5.25% · 107650@5.5% · 269300@6% · 1616450@6.85% · 5000000@9.65% · 25000000@10.3% · null@10.9%

---

## 2. 重要税务限制(MVP 估算,明确标注,不伪装确定)

- **NY tax benefit recapture**：NYAGI > **$107,650** 的纳税人有"补充税",把低档优惠收回。本步**只建边际档位、不建 recapture** → 对超过 $107,650 的 NY 估算会**偏低**。必须在 `notes`/`assumptions` 写明,黄金值只取 ≤ $107,650(此时边际=实际)。
- **CA 心理健康附加税**：应税收入 > $1,000,000 额外 +1%（Mental Health Services Tax）。本步**不建**,对 >$1M 偏低,标注。
- **CA <$100,000**：官方要求用 Tax Table(分段查表,带四舍五入);引擎统一用税率表公式,>$100k 完全一致,≤$100k 有微小取整差。标注为估算。
- MFS 用 single 表、QSS 用 MFJ 表(CA/NY 官方分组一致)。

---

## 3. 各层改动

### 3.1 数据 `data/tax_years/2025/us_states.json`
CA、NY 两个条目从 `pending_extraction` 改为：
```jsonc
"CA": {
  "name": "California", "income_tax_type": "progressive", "status": "effective",
  "effective_date": "2025-01-01",
  "source_ids": ["ca_2025_540_tax_rate_schedules"],
  "citation": "2025 California Tax Rate Schedules (FTB), Schedules X/Y/Z.",
  "brackets": { "single":[...], "married_filing_separately":[...], "married_filing_jointly":[...],
                "qualifying_surviving_spouse":[...], "head_of_household":[...] },
  "notes": "Base rate schedule only; 1% Mental Health Services Tax over $1,000,000 not modeled (MVP estimate)."
}
"NY": { ... 同结构 ..., "notes": "Marginal brackets only; tax benefit recapture above $107,650 NYAGI not modeled (estimate understates above that)." }
```
（brackets 用 §1 的精确值；末档 `up_to: null`。）

### 3.2 引擎 `engine/tax_engine.py`：`state_income_tax`
- **签名加 `filing_status`**：`state_income_tax(state_code, taxable_income, filing_status="single", tax_year=2025)`（默认 single,向后兼容 flat/零税州调用）。
- 新增 **`income_tax_type=="progressive"` 分支**：经 `_normalize_filing_status` 取 `state["brackets"][filing]`，用 `bracket_tax(max(0,taxable_income), brackets)` 计税;返回结构同 flat（state/tax/rate→这里 rate 可省或给 "progressive"）+ citations + assumptions（含 §2 对应州的限制说明）。
- flat/none/拒算分支不变。

### 3.3 API `backend/schemas.py` + 路由
- `StateIncomeRequest` 加 `filing_status: FilingStatus = "single"`。
- 路由透传(已是 `**payload.model_dump()`,自动带上)。

### 3.4 前端 `frontend/index.html`
- 个人所得税模块调 `/calc/state-income` 时**带上 filing_status**(模块里已有 `filing` 变量);其余不变。CA/NY 不再显示 not_covered,而显示真实州税 + citation。

### 3.5 校验 `tests/validate_step1_data.ps1`
- CA/NY 现在 `status==effective`：原有"effective 必有 effective_date / source_ids 解析"会自动覆盖;**新增**:progressive 州必须含 `brackets` 且 5 种申报身份齐全、每档末位 `up_to=null`。
- 注意:之前有"pending/source_pending 不得带 flat_rate/brackets"的守卫;CA/NY 现在 effective+progressive 带 brackets 是合法的,确认守卫不误伤。

---

## 4. 黄金用例(期望值已手算，2025)
`tests/golden/state_income_tax.json` 新增(并把原 CA/NY 的 not_covered 用例改为 ok）：
| name | 输入 | 期望 tax | 说明 |
|---|---|---|---|
| ca_single_200k | CA, 200000, single | **15038.64** | 9.3% 档 |
| ca_mfj_125k | CA, 125000, mfj | **4768.10** | 官方示例值,逐分对齐 |
| ny_single_100k | NY, 100000, single | **5431.75** | <107,650,无 recapture,准确 |
| ny_mfj_100k | NY, 100000, mfj | **5167.50** | <107,650,准确 |
（NY 黄金一律取 ≤107,650,避免 recapture 缺失导致的偏差进入基线。）
另:`tests/test_engine.py` 加边界单测——CA single 应税 0 → 0；progressive 州缺 filing_status 默认 single。

---

## 5. 交付物与分工
- **Codex**：改 `us_states.json`(CA/NY)、`state_income_tax`(加 filing_status+progressive)、`schemas.py`、`frontend/index.html`(state 调用带 filing_status)、`validate_step1_data.ps1`、`tests/golden/state_income_tax.json`、`tests/test_engine.py`；设计文档一并提交;交付记录 `docs/step1_2_ca_ny_state.md`。纯函数、只读 JSON、无裸写税率(全部从 us_states.json 读)、复用 `bracket_tax`。分支 `feature/step1_2-ca-ny-state`，PR 到 main，CI 绿。
- **Claude**：本设计 + 已核验数据；实现后独立重算 CA/NY 黄金值逐分对齐 + 浏览器/headless 验证前端 CA/NY 出真实税额 + 查 not_covered 守卫未误伤 + 根 index.html 未变。
- **Shaw**：合并 PR。

## 6. 退出门槛
- [ ] CA/NY 在 `us_states.json` 为 `progressive`+`effective`，5 申报身份 brackets 齐全,数值=§1。
- [ ] `state_income_tax` 支持 filing_status + progressive；flat/零税/拒算路径无回归。
- [ ] API `/calc/state-income` 接受 filing_status；前端调用带上。
- [ ] 黄金值逐分对齐(ca_mfj_125k=4768.10 等)；CA/NY 旧 not_covered 用例改为 ok。
- [ ] §2 限制(NY recapture、CA MHS、CA<100k)在 notes/assumptions 写明。
- [ ] ruff + unittest + 数据校验 + pip-audit CI 全绿；根 index.html hash 未变。
- [ ] Claude review 通过([Blocker]/[Major]/[Minor])。

## 7. 范围外
NY recapture、CA 1% MHS over $1M、CA Tax Table 取整、MA/TX/WA 来源、其余前端模块接后端、income_tax_summary——均属后续。
