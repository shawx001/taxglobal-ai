# Step 2.4 交付记录 — QBI 扣除引擎(§199A)

日期：2026-06-02
分支：`feature/step2_4-qbi-engine`

## 目标

实现纯函数 `qbi_deduction`,把 Step 1.3 的 `us_qbi.json` 数据接入引擎。函数只计算 §199A QBI 扣除额,不计算所得税、不串自雇总税。

## 改动

- `engine/rules_loader.py`:新增 `load_qbi_rules`。
- `engine/tax_engine.py`:新增 `qbi_deduction`,使用 Decimal、读取 `us_qbi.json`、支持 threshold / phase-in / above-upper 三段逻辑。
- `engine/__init__.py`:导出 `qbi_deduction`。
- `data/tax_years/2025/us_qbi.json`:补充 W-2/UBIA 限制比例,避免引擎裸写规则比例。
- `tests/golden/qbi_deduction.json`:新增 8 个黄金用例,覆盖阈值以下、整体上限、超限、非 SSTB phase-in、SSTB phase-in。
- `tests/test_engine.py`:新增 qbi=0、负 qbi clamp、TI 等于阈值边界测试。
- `tests/validate_step1_data.ps1`:新增 W-2/UBIA 限制比例校验。

## 已知限制

- SSTB 行业判定由调用方传入 `is_sstb`,本函数不判断行业。
- UBIA 合格性和财产细节由调用方给数,本函数不建模。
- REIT/PTP 的 §199A 组成部分不在本步处理。
- 完整自雇总税仍待 `income_tax_summary` 串联。
