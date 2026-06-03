# Step 5.4 交付记录 — 自雇前端接 `income_tax_summary`

日期:2026-06-02
分支:`feature/step5_4-se-frontend`

## 目标

把前端自雇模块从原型假算迁移到后端 `income_tax_summary`,一次性展示自雇税、联邦所得税、精确州税、总税额和季度预缴。

## 改动

- `backend/schemas.py`:新增 `IncomeSummaryRequest`。
- `backend/routes/calc.py`:新增 `POST /calc/income-summary`,薄封装 `income_tax_summary`。
- `frontend/api.js`:新增 `TaxGlobalApi.incomeSummary(payload)`。
- `frontend/index.html`:自雇表单新增所在州和申报状态选择器;`calcSE` 改为 async 后端调用并渲染引擎返回字段。
- `frontend/index.html`:档案同步时普通收入模块改用 W-2 wages,自雇/ecom 收入带入自雇模块,避免同一笔收入在普通收入和自雇模块重复计税。
- `tests/test_api_calc.py`:新增 `/calc/income-summary` CA/FL/MA/非法 filing 测试,并纳入 OpenAPI 路径检查。
- `docs/product_backlog.md`:REQ-002/REQ-003 更新为部分推进。
- `docs/feature_status.md`:新增 Step 5.4 状态和文档索引。

## 验收重点

- CA single, net self-employment profit 100000:total_tax 27311.11,state tax 4550.96,federal 8630.60。
- FL single, net self-employment profit 100000:total_tax 22760.15,state tax 0。
- MA single, net self-employment profit 100000:顶层 ok,嵌套 state_income_tax.status 为 not_covered,total_tax 22760.15。
- 自雇前端不再调用 `caStateTax` / `nyStateTax`;这两个旧函数仍保留给尚未迁移的旧原型模块。
- 根 `index.html` 未修改。

## 已知限制

- 本步只迁移自雇模块;6 国对比、旧 W-2/州税原型仍可能使用 `caStateTax` / `nyStateTax`,待后续迁移时删除。
- 档案同步已覆盖 W-2 与自雇/ecom 收入分流;更完整的档案持久化、更多收入桶和跨模块合并仍待后续步骤实现。
- `income_tax_summary` 的州级残余调整限制沿用 Step 2.5 assumptions。
