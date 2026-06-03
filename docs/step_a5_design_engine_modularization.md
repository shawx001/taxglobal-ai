# Step A.5 设计文档 — 引擎模块化重构(行为不变)

日期：2026-06-03
阶段：PLM 阶段 2（Design）/ 技术债治理（防屎山）
依据：`engine/tax_engine.py`(~1820 行的"上帝文件")；2025+2026 完整 golden 测试集。
分支：`feature/engine-modularization`(基于 #25 合并后的 main)
角色：Claude 出设计 + review(确认零行为变化);Codex 实现;Shaw 拍板。
工程标准：**纯重构,行为不变**——goldens 全绿即证明零行为改变;不改任何公式、签名、数值、返回结构。

> 目标:把单文件 `tax_engine.py` 按领域拆成 `engine/` 包内多个小模块,建立分层依赖 + 公共门面,**不改一行计算逻辑**。现在 2025+2026 golden 覆盖最全,是做行为不变重构最安全的窗口;趁 Step B(扩州)/Step C(前端)堆更多代码前先拆。

---

## 0. 硬约束(本步的生命线)
1. **逐字搬运,零逻辑改动**:函数体一字不改(连空白/注释/顺序都尽量保留),只是移动到新文件 + 补 import。审查时每个函数体应与原文件**字符级一致**。
2. **公共 API 不变**:所有现在能 `from engine import X` 的名字继续可用(门面 `engine/__init__.py` 重新导出)。
3. **零破坏**:保留 `engine/tax_engine.py` 作为**兼容 shim**(从新子模块 re-export 全部公有+私有名,含 `_state_taxable_base` 等),这样 `from engine.tax_engine import _state_taxable_base`(tests/test_engine.py:17)等仍可用,不用改测试。
4. **无数值/签名/返回结构变化**;不引入新依赖;不改 `rules_loader.py`、数据文件、前端。
5. **退出门槛**:`unittest` 全绿(2025+2026 golden 逐分不变)、ruff、数据校验、`git diff --check`、两份 index.html hash 不变。

## 1. 目标包结构(分层,避免循环 import)
**基础层(不依赖任何 engine 模块)**
- `engine/money.py`：`_money` `_money_decimal` `_money_quantized` `_decimal_rule` `_decimal_input`
- `engine/responses.py`：`_response` `_not_covered` `_invalid_input` `_citations` `_merge_citations`
- `engine/filing.py`：`SUPPORTED_FILING_STATUSES` `FILING_ALIASES` `_normalize_filing_status`
- `engine/brackets.py`：`bracket_tax` `_bracket_tax_decimal` `_long_term_capital_gains_tax`（被 summary 与 crypto 共用，必须放共享层）
- `engine/dates.py`：`_parse_iso_date` `_add_one_calendar_year`

**领域层(依赖基础层 + `rules_loader`)**
- `engine/federal.py`：`federal_income_tax`
- `engine/payroll.py`：`fica_tax` `self_employment_tax` `_combined_payroll`
- `engine/qbi.py`：`qbi_deduction`
- `engine/feie.py`：`feie_estimate`
- `engine/state.py`：`state_income_tax` `_state_taxable_base`
- `engine/crypto.py`：`SUPPORTED_CRYPTO_METHODS` `_capital_gains_rule_version` `_net_capital_gains` `_validate_crypto_item` `_validate_crypto_inputs` `_sort_crypto_lots` `_match_crypto_lots` `_crypto_tax_estimate` `_crypto_state_not_covered` `_crypto_state_tax` `crypto_gain_estimate`
- `engine/rsu.py`：`_validate_sale_scenario` `rsu_tax_estimate`
- `engine/nexus.py`：`NEXUS_APPROACHING_RATIO` `_compare_threshold` `nexus_estimate`

**编排层**
- `engine/summary.py`：`_summary_rule_version` `income_tax_summary`（**逐字搬运**;从领域层/基础层 import 它用到的 payroll/qbi/feie/state/federal-brackets/responses 等）

**门面 / 兼容**
- `engine/__init__.py`：re-export 公共 API（`bracket_tax` `federal_income_tax` `fica_tax` `self_employment_tax` `qbi_deduction` `feie_estimate` `state_income_tax` `crypto_gain_estimate` `rsu_tax_estimate` `nexus_estimate` `income_tax_summary` 等，与现状一致）。
- `engine/tax_engine.py`：兼容 shim，`from engine.<mod> import *`（含私有名）re-export,顶部注释「deprecated: 改从 engine 或子模块导入」。后续单独 PR 清理直接 import。

> 依赖方向严格单向:基础层 ← 领域层 ← 编排层 ← 门面。不得出现领域层互相 import 成环(如有共用 helper,下沉到基础层)。

## 2. 不在本步做(明确划界,防 scope 蔓延)
- **不**把 `income_tax_summary` 拆成 pipeline 阶段(那是更大的内部重构,风险更高)——本步只把它**整体**搬进 `summary.py`,留作可选的 Step A.6。
- **不**改任何税率/阈值/公式/签名/返回结构。
- **不**动 `rules_loader.py`、数据、前端、backend(backend 走 `engine` 门面,不受影响)。

## 3. 审查与验收(Claude)
- `git diff` 逐函数核对:每个搬运的函数体与原 `tax_engine.py` **字符级一致**(只允许 import 行 + 文件归属变化)。
- 全测试 + 2025/2026 golden 逐分不变;ruff(import 排序/未用导入)通过;数据校验通过;`git diff --check`;两份 index.html hash 不变。
- 公共 API 冒烟:`from engine import income_tax_summary, crypto_gain_estimate, ...` 全部可导入;`from engine.tax_engine import _state_taxable_base` 仍可用(shim)。
- 抽若干场景(含 2026 anchor 51073、A–E)经新结构仍逐分不变。

## 4. 交付物与分工
- **Codex**:按 §1 拆分 `engine/` 包(逐字搬运)+ `__init__.py` 门面 + `tax_engine.py` shim;更新必要的内部 import;交付记录 `docs/step_a5_engine_modularization.md`;更新 `feature_status.md` / `coding_standards.md`(加「引擎=门面后的小模块;新州/年=只改数据;规则永不裸写进代码」约定)。分支 `feature/engine-modularization`,PR→main,CI 绿。
- **Claude**:本设计 + review(逐函数字符级核对 + 全 golden 逐分不变 + 公共 API 冒烟)。
- **Shaw**:拍板、合并。

## 5. 之后
- (可选)Step A.6：`income_tax_summary` → `TaxContext` + pipeline 阶段(加收入类型=加一段,不改长函数)。
- Step B：扩州(NJ/OR/PA + WA 资本利得 excise)——**数据驱动 + 注册表**,落在新 `engine/state.py` 里。
- Step C：前端 RSU 独立桶 + 发 `tax_year=2026`。
- `coding_standards.md` 固化反屎山约定。
