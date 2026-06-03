# REQ-002 前端合并计税总览交付记录

## 目标

把「税务计算 / 普通收入」从前端分别调用 federal/FICA/state 后相加，改为档案输入一次调用 `/calc/income-summary`，由引擎统一处理 W-2、自雇、QBI、资本利得、NIIT、FEIE 和州税叠加。

## 改动

- `frontend/index.html`
  - 普通收入表单扩展为合并档案总览。
  - `calcTax()` 改为单次 `TaxGlobalApi.incomeSummary(payload)`。
  - 渲染引擎返回的 `total_tax`、`breakdown`、`citations`、`assumptions`。
  - 保留 request sequence 防竞态；空值不入 payload，金额夹零，`days_abroad` 错误如实显示。
- `scripts/run_overview_dev.py`
  - 一条命令启动 FastAPI `:8000` 和静态前端 `:5173`，自动打开浏览器，退出时清理进程。
- `tests/test_integration_income_summary.py`
  - 锁定四个前端总览 payload 的黄金总税和关键 breakdown。
- `docs/req002_overview_manual_checklist.md`
  - 人工浏览器点验清单和表单 id 到引擎参数映射。

## 验收场景

- A 工资+长期利得: total tax `60465.20`
- B FEIE: excluded income `130000.00`, total tax `13200.00`
- C 自雇+长期利得+FEIE: QBI `8152.23`, total tax `19875.71`
- D 自雇+CA: total tax `27311.11`, CA state tax `4550.96`

## 已知边界

- RSU、crypto、nexus、独立 FEIE 页面仍是单模块 what-if，本步只改普通收入总览。
- FTC、州级 FEIE 差异、资本亏损结转等仍由引擎 assumptions 如实提示。
- 未覆盖州不静默归零；界面显示 reason，合并总税只包含引擎已覆盖部分。
