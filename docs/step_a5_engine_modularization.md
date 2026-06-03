# Step A.5 引擎模块化重构交付记录

日期：2026-06-03
分支：`feature/engine-modularization`

## 目标

把 `engine/tax_engine.py` 从单一上帝文件拆成按职责分层的小模块，同时保持行为不变。公共 API 保持兼容：`from engine import ...` 继续可用，`from engine.tax_engine import _state_taxable_base` 等旧私有导入也继续可用。

## 改动范围

- 新增基础层：
  - `engine/money.py`
  - `engine/responses.py`
  - `engine/filing.py`
  - `engine/brackets.py`
  - `engine/dates.py`
- 新增领域层：
  - `engine/federal.py`
  - `engine/payroll.py`
  - `engine/qbi.py`
  - `engine/feie.py`
  - `engine/state.py`
  - `engine/crypto.py`
  - `engine/rsu.py`
  - `engine/nexus.py`
- 新增编排层：
  - `engine/summary.py`
- 更新门面：
  - `engine/__init__.py` 直接从新模块 re-export 公共 API。
  - `engine/tax_engine.py` 改成 deprecated compatibility shim，re-export 旧入口需要的公有和私有名。

## 行为不变保证

- 所有搬运的函数体从原 `engine/tax_engine.py` 机械抽取。
- 搬运后使用脚本逐函数对比，确认函数体与原文件字符级一致（忽略换行符平台差异）。
- 未改任何税率、阈值、公式、函数签名、返回结构、数据文件、后端 schema、前端。

## 分层说明

- 基础层不依赖其他 engine 模块。
- 领域层只依赖基础层和 `rules_loader`。
- `summary.py` 作为编排层调用领域层函数，不拆 `income_tax_summary` pipeline。
- `tax_engine.py` 只保留兼容 shim，避免旧导入立刻断裂。

## 验收

- 字符级函数体搬运对比：通过。
- `python -m unittest discover -s tests -v`：84 tests OK。
- `ruff check engine backend tests`：通过。
- 公共 API 冒烟：
  - `from engine import income_tax_summary, crypto_gain_estimate, rsu_tax_estimate, nexus_estimate, state_income_tax, qbi_deduction, feie_estimate, federal_income_tax, fica_tax, self_employment_tax, bracket_tax`
  - `from engine.tax_engine import _state_taxable_base`
- 数据校验 / diff check / hash：提交前复跑。

## 已知限制

- 本步没有拆 `income_tax_summary` 的内部 pipeline；后续可在 Step A.6 做 `TaxContext` / pipeline 化。
- 本步没有改 `rules_loader.py`、数据文件、backend、frontend。
