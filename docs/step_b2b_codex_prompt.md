# Codex Prompt — Step B2b：加 Oregon(OR)州所得税(联邦税减项 + 阶梯退坡)

> 复制以下内容给 Codex。先读 `/AGENTS.md`、`/ARCHITECTURE.md`、`docs/step_b2b_design_or_state.md`。**前置:基于已合并 #29 的最新 `main` 新建分支 `feature/step-b2b-or`。** 一步一 PR。

## 背景与铁律
- 报税计算引擎,真实上线导向。**数值精确到分(Decimal, ROUND_HALF_UP);税率/参数只来自 `data/tax_years/YYYY/`,永不硬编码;新州=只改数据 + 通用引擎逻辑,严禁州名特判(no `if state == "OR"`)。**
- 默认 `tax_year=2026`;OR 参数为 2025 值,数据块标 `state_parameter_year: 2025`。
- 模块化(no-monolith);无状态/幂等;改完自查门禁全绿;不自我认证。

## 目标
加 **OR(累进所得税)**:OR 应税基 = 联邦 AGI − OR 标准扣除 − **联邦所得税减项**;减项 = `min(联邦所得税额, 上限)`,上限随 AGI **阶梯退坡**(ORS 316.800 为阶梯式,非线性)。

## 实现要求

### 1. 引擎 `engine/summary.py`
- 新增 OR 减项基准:`federal_income_tax_liability = federal_income_tax + long_term_capital_gains_tax`(联邦"所得税"=普通+资本利得税;**不含 NIIT/SE/工资税**)。
- 调 `_state_taxable_base(...)` 时新增传参 `federal_income_tax=federal_income_tax_liability`。

### 2. 引擎 `engine/state.py` `_state_taxable_base`
- 函数签名加形参 `federal_income_tax: Decimal`(放在现有 keyword-only 形参组里,给默认 `Decimal("0")` 以兼容其它州调用,但 summary 必须显式传)。
- 在 `start_from == "federal_agi"` 分支,支持**新配置** `tax_base["federal_tax_subtraction"]`(通用,数据驱动):
  ```
  base = federal_agi - _decimal_rule(standard_deduction[filing])   # 现有逻辑
  fts = tax_base.get("federal_tax_subtraction")
  if fts:
      steps = fts["phaseout_table"][filing]          # 升序 list[{agi_up_to, limit}]
      limit = next(_decimal_rule(s["limit"]) for s in steps
                   if s["agi_up_to"] is None or federal_agi <= _decimal_rule(s["agi_up_to"]))
      subtraction = min(federal_income_tax, limit)
      base -= subtraction
  return max(Decimal("0"), base)
  ```
  **阶梯退坡 = 数据表查找,无硬编码档位、无州名特判。** 最后一档 `agi_up_to: null, limit: 0`。
- 不破坏现有 federal_agi 分支对其它州(CA/NY/GA/IL/CO)的行为(无 `federal_tax_subtraction` 配置时逻辑不变)。

### 3. 数据 `data/tax_years/2025/us_states.json` 与 `2026/us_states.json`
加 **OR**(2026 文件标 `state_parameter_year: 2025`):
```
"income_tax_type": "progressive",
"tax_base": {
  "start_from": "federal_agi",
  "allows_qbi": false,
  "capital_gains_treatment": "ordinary_income",
  "standard_deduction": { "single": "2835", "married_filing_jointly": "...", "head_of_household": "...", "married_filing_separately": "...", "qualifying_surviving_spouse": "..." },
  "federal_tax_subtraction": {
    "phaseout_table": {
      "single": [ {"agi_up_to": "<step1>", "limit": "8500"}, ... , {"agi_up_to": null, "limit": "0"} ],
      "married_filing_jointly": [ ... ],
      "head_of_household": [ ... ],
      "married_filing_separately": [ {"agi_up_to": "...", "limit": "4250"}, ... ],
      "qualifying_surviving_spouse": [ ... ]
    }
  }
},
"brackets": { "single": [...], "married_filing_jointly": [...], ... }
```
- **档位(已核验,单身 2025)**:4.75% ≤4,400 / 6.75% ≤11,050 / 8.75% ≤125,000 / 9.9% 以上。其余 filing status 档位、标准扣除、退坡阶梯表 **必须从官方 Oregon DOR Form OR-40 instructions(2025)联邦税减项工作表 + Pub OR-17 逐项录入**,带 `source_ids`,并在 `data/sources/us/2025/` 归档原件 + 更新 `source_manifest.json`(content_hash)。
- 退坡表每个 filing status 升序排列、覆盖到 `agi_up_to: null`。MFS 上限 4,250。

### 4. 黄金值 `tests/golden/income_tax_summary_2026.json`
- **OR W-2 100,000 single(已 Claude 独立逐分核;减项满额、AGI 低于退坡起点)**:
  联邦 13,170.00 / 工资税 7,650.00 / 联邦税额 13,170 → 减项 min(13,170, 8,500)=8,500 / OR 税基 100,000−2,835−8,500=88,665 / **OR 州税 7,449.19 / total 28,269.19**。
- 再加 1 个**退坡区内**用例(single AGI 在 \$125k–\$145k),按你录入的阶梯表产出(将由 Claude 对照 OR-40 工作表逐分核)。

### 5. 测试 `tests/test_engine.py`
- OR:减项满额(AGI < 退坡起点)、退坡分档命中、AGI ≥ 退坡终点 → 减项 0、MFS 上限 4,250。
- 回归:CA/NY/GA/IL/CO/WA/NJ/PA + 联邦 + FL/NV(无税)全不变。

### 6. 数据校验 `tests/validate_step1_data.ps1`
- 校验 OR 的 `federal_tax_subtraction.phaseout_table`:各 filing status 存在、为升序 list、末档 `agi_up_to=null`、limit/agi 可解析为 Decimal。**确保 2025 与 2026 两个税年都被校验到**(此前 2026 循环较浅)。

### 7. 文档
- 写 `docs/step_b2b_or.md`(交付记录:改了什么、数源、黄金值、假设/未建模:OR 减项用联邦所得税近似口径、kicker/抵免未建模)。
- 更新 `docs/feature_status.md`、`docs/product_backlog.md`、`docs/roadmap_skills_status.md`、**根 `project.md`**(州覆盖加 OR、当前进度推进)。

## 验收门槛(全绿才开 PR)
- `python -m unittest discover -s tests` 全过(含新 OR 用例 + 回归)。
- `python -m ruff check engine backend tests` 0 error。
- `powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1` 通过(含 OR 退坡表 shape,2025+2026)。
- `git diff --check` 无空白错误;两份 `index.html`(根 + frontend)hash 不变。
- 自查清单:无州名特判、无硬编码税率;summary 正确传 `federal_income_tax`(=联邦+LTCG,不含 NIIT/SE);OR W-2 100k single 命中 7,449.19 / 28,269.19。

## PR
- 分支 `feature/step-b2b-or` → PR 到 `main`,标题 `Step B2b: add Oregon (OR) state income tax with federal-tax subtraction`,正文列改动 + 数源 + 黄金值 + 假设;CI 绿。**等 Shaw 合并,勿自合。**
