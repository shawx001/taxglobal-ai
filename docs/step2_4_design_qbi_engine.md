# Step 2.4 设计文档 — `qbi_deduction` 引擎(§199A)

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：Step 1.3 `us_qbi.json`、`engineering_process.md`、`tax_rules_self_employment.md`、IRS Form 8995/8995-A
分支：`feature/step2_4-qbi-engine`
角色：Claude 出设计 + 已手算黄金值;Codex 实现。

> 目标:把 QBI 数据变成纯函数 `qbi_deduction`。**§199A 是美国税法最复杂条款之一**,所以分层保证正确:阈值以下精确;阈值以上按 W-2 工资/UBIA/SSTB 限制 + phase-in。全程 Decimal、只读 `us_qbi.json`、不裸写税率。

---

## 1. 函数契约
```
qbi_deduction(
    qbi: float,                       # 合格经营收入(已减 ½SE税等)
    taxable_income: float,            # 应税收入(算 QBI 前、减标准/分项后)
    filing_status: str = "single",
    net_capital_gain: float = 0.0,    # 用于整体 20% 上限
    w2_wages: float = 0.0,            # 经营体支付的 W-2 工资(阈值以上才用)
    ubia: float = 0.0,                # 合格财产未调整基(阈值以上才用)
    is_sstb: bool = False,            # 是否特定服务业(律师/咨询/健康等)
    tax_year: int = 2025,
) -> dict
```
`result`：`{deduction, qbi_component, overall_limit, applied_limit, threshold_band}`。
`applied_limit` ∈ `below_threshold | phase_in | wage_ubia_limited | sstb_excluded | overall_income_capped`。
`rule_version` = `us-2025-qbi-v0.1`;citations 取 us_qbi source_ids。

## 2. 算法(§199A,全程 Decimal)
读 `us_qbi`: `rate=0.20`, `thr=threshold[filing]`, `win=phase_in_window[filing]`, `upper=upper_limit[filing]`。
```
tentative   = 0.20 × max(0, qbi)
overall_cap = 0.20 × max(0, taxable_income − net_capital_gain)
wage_ubia   = max(0.50×w2_wages, 0.25×w2_wages + 0.025×ubia)
```

**A. 阈值以下(taxable_income ≤ thr):** 不做 W-2/SSTB 测试(法定):
`deduction = min(tentative, overall_cap)` → applied_limit = below_threshold(或 overall_income_capped)

**C. 完全超限(taxable_income ≥ upper):**
- `is_sstb` → `deduction = 0`(sstb_excluded)
- 否则 → `deduction = min( min(tentative, wage_ubia), overall_cap )`(wage_ubia_limited)

**B. phase-in 区间(thr < taxable_income < upper):** `ratio = (taxable_income − thr)/win`
- 非 SSTB:`excess = max(0, tentative − wage_ubia)`;`reduction = excess × ratio`;`component = tentative − reduction`;`deduction = min(component, overall_cap)`
- SSTB(**最复杂,Form 8995-A 口径**):`applicable% = 1 − ratio`;按 `applicable%` 缩放 qbi/w2/ubia 后,再走上面非 SSTB 的 phase-in 公式。

## 3. 设计决策
- **QBI-1** `w2_wages/ubia/is_sstb` 可选(默认 0/0/False)→ **独资无雇员的常见情形,阈值以上 wage_ubia=0 → 扣除自动=0,这是法律上的正确结果**,不是近似。
- **QBI-2** 阈值以下精确,覆盖多数自雇个人(数值正确)。
- **QBI-3** 阈值以上/phase-in 按 §199A 实现;**SSTB 的 phase-in 是最易错的一段**,golden 必须覆盖,assumptions 注明"复杂情形建议专业核对"。
- **QBI-4** 纯函数、Decimal、只读 JSON;只算"扣除额",不碰所得税本身(那由 income_tax_summary/federal 串)。
- **QBI-5** 输入校验:负值 clamp 到 0;未知 filing_status 经 `_normalize_filing_status`。

## 4. 黄金用例(期望值已手算,single,2025;thr 197300 / win 50000 / upper 247300)
| name | qbi | TI | 其他 | 期望 deduction | 说明 |
|---|---|---|---|---|---|
| below_simple | 50000 | 100000 | — | **10000.00** | 20%×50000,未触整体上限 |
| below_ti_capped | 50000 | 40000 | — | **8000.00** | 整体上限 20%×40000 binding |
| below_ncg_binds | 50000 | 100000 | ncg=90000 | **2000.00** | 20%×(100000−90000) |
| above_nonsstb_no_wages | 50000 | 300000 | w2=0 | **0.00** | wage 上限 0(独资无雇员的正确结果) |
| above_nonsstb_with_wages | 100000 | 300000 | w2=40000 | **20000.00** | wage 上限 max(20000,10000)=20000 |
| above_sstb | 100000 | 300000 | sstb=True | **0.00** | SSTB 超限完全剔除 |
| phase_in_nonsstb | 100000 | 222300 | w2=0 | **10000.00** | ratio 0.5;20000−(20000−0)×0.5 |
| phase_in_sstb | 100000 | 222300 | sstb=True,w2=0 | **5000.00** | applicable% 0.5→qbi 50000→10000−5000(⚠️ 最复杂,重点核) |
边界单测:qbi 0 → 0;负 qbi → 0;TI 恰好等于 thr → 走阈值以下。

## 5. 验收
- 引擎独立重算上 8 例逐分对齐(尤其 phase_in_sstb)。
- 纯函数/只读 JSON/无裸写税率(grep)。
- ruff + unittest + 数据校验 + pip-audit CI 全绿;根 index.html hash 未变。
- Claude review 通过([Blocker]/[Major]/[Minor]),重点核 phase-in 与 SSTB 两段。

## 6. 交付物与分工
- **Codex**:`engine/tax_engine.py` 加 `qbi_deduction` + helper;`rules_loader.py` 加 `load_qbi_rules`;`__init__` 导出;`tests/golden/qbi_deduction.json`(照 §4);`tests/test_engine.py` 边界单测;设计 + 交付记录 `docs/step2_4_qbi_engine.md`。纯函数、Decimal、复用 `_response`/`_invalid_input`。分支 `feature/step2_4-qbi-engine`,PR 到 main,CI 绿。
- **Claude**:本设计 + 手算黄金值;实现后逐分核对(尤其 SSTB phase-in)+ 查无裸写税率。
- **Shaw**:合并 PR。

## 7. 范围外 / 已知限制
- SSTB 的精确判定(哪些行业属 SSTB)由调用方传 `is_sstb`,本函数不做行业分类。
- UBIA 的折旧期/合格财产判定不建模(调用方给数)。
- REIT/PTP 收入的 20% 那部分(§199A 另一组成)本步不做。
- 本函数只给"扣除额";完整自雇/经营总税待 **Step 2.5 `income_tax_summary`** 串起来。

## 8. 之后
Step 2.5 `income_tax_summary`:净利润 → ½SE税 → (健保/退休) → QBI(本函数) → 标准/分项 → 联邦累进 + 州税 + SE税 = 总税;前端(Step 5.4)展示完整正确的自雇总税。
