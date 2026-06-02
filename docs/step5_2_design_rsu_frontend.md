# Step 5.2 设计文档 — RSU 面板接后端 `/calc/rsu`

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：Step 2.3 `rsu_tax_estimate`、Step 4 API、Step 5 前端模式、`coding_standards.md`
分支：`feature/step5_2-rsu-frontend`
角色：Claude 出设计；Codex 实现。

> 目标：把前端 RSU 面板从"原型假算"改为调用 `/calc/rsu`,显示后端真实结果 + 法条。消化上轮 Minor（RSU tab 默认可见却跑前端假算）。只动 RSU 面板 + api.js;不动根 index.html、不动其余模块、前端不算税。

---

## 1. 输入重塑(原型字段 → 后端契约)

后端 `/calc/rsu` 请求(FastAPI schema): `shares_vested, fmv_per_share, vest_date, filing_status, other_taxable_income, sale_scenario?`。
路由层会把 `fmv_per_share` 映射到引擎参数 `fair_market_value_per_share`。

| 原型面板字段 | 处置 |
|---|---|
| `rsu-base` 基础工资 180000 | → 复用为 `other_taxable_income`(把 RSU 普通收入叠到正确税档) |
| `rsu-vest` RSU 归属价值($) | **拆成两个输入**:`shares_vested`(股数) + `fmv_per_share`(归属 FMV) |
| `rsu-opt` 未行权期权价值 | **移除**(期权 ≠ RSU,后端不建模;→ backlog REQ-006 股票期权模块) |
| `rsu-growth` 预期涨幅滑块 | **移除**(我们 Step 2.3 定:不投机未来股价) |
| (新增) `vest_date` | 归属日期(ISO,默认本税年) |
| (新增,可选) 卖出场景 | toggle:`sale_date` + `sale_price_per_share` → 触发"持有转 LTCG vs 立即卖"对比 |
| (新增) `filing_status` | 取自档案/共享申报身份选择器 |

> 这些改动都是**为了不伪装确定性**:原型的"涨幅滑块×0.20"是假算,后端用显式卖出场景 + 数据驱动税率替代;期权属另一套规则,不混入。

## 2. api.js
新增 helper:`rsu: function(payload){ ... }`。它会把前端语义字段 `fair_market_value_per_share` 归一化为后端请求字段 `fmv_per_share`,再 `POST /calc/rsu`。复用现有 service_unavailable / request_failed / invalid_response 处理。

## 3. 计算流程与展示(前端只编排)
1. 收集:shares_vested、fair_market_value_per_share(UI 语义字段,发送前归一化为 fmv_per_share)、vest_date、filing_status、other_taxable_income;若开了卖出场景则带 `sale_scenario:{sale_date, sale_price_per_share}`。
2. 调 `/calc/rsu` → 后端返回 `result.vesting`(ordinary_income / vest_income_tax / cost_basis_per_share)+ `result.hold_vs_sell`(可空)。
3. 展示(全部经 `escapeHtml`,复用 Step 5.1):
   - 归属普通收入、归属带来的所得税(+ citations + assumptions)
   - 若有卖出场景:资本利得、长/短期、资本利得税、对比说明
   - **带出后端 assumptions**——尤其"RSU 归属还需缴 FICA,见 fica_tax""卖出价为输入非预测"
4. 错误:invalid_input(如股数≤0/日期非法/卖出日期早于归属)→ 显示后端 message;后端不可用 → "服务不可用"。

## 4. 设计决策
- **RSU-1** 拆 shares × fmv(更准,且使卖出对比可算)。
- **RSU-2** 移除涨幅滑块(无投机)+ 期权字段(非 RSU);期权→ backlog **REQ-006**。
- **RSU-3** other_taxable_income 用原 base 工资字段(可手填);后续 REQ-001 收入分桶后改为自动带入。
- **RSU-4** 复用 Step 5.1 的 escapeHtml + api.js 错误处理;前端不算税。

## 5. Backlog 新增（本步加入 `product_backlog.md`）
```
| REQ-006 | 股票期权(NQSO/ISO/ESPP)单独模块 | 待引擎+数据 | 🟢 | RSU 面板移除了"未行权期权价值"输入。期权与 RSU 税务规则不同(行权价、AMT、持有期等),需独立数据+引擎,不混入 RSU。本步只移除,记录待后续。 |
```

## 6. 验收(诚实标注边界)
- 手动/headless:RSU 面板填 股数+FMV+归属日期+其他收入 → 显示后端 归属普通收入 + 所得税 + 法条;开卖出场景(持有>1年)→ 显示长期资本利得税 + 对比。
- Claude review 会 headless 复现面板的 `/calc/rsu` 调用序列,核对返回值(沿用 Step 2.3 已验证的引擎:如 1000 股@$50 + other 150000 → vest_income_tax 12216.00)。
- 前端无 JS 自动化框架,仍以代码评审 + 手动为主(后续基建)。
- 全套:unittest / ruff / pip-audit / 数据校验 全绿;根 index.html hash 未变。

## 7. 交付物与分工
- **Codex**:`frontend/index.html`(RSU 面板输入重塑 + `calcRSU` 改调 `/calc/rsu` + 经 escapeHtml 展示;移除涨幅滑块/期权字段/旧 calcRSU 假算)、`frontend/api.js`(加 rsu helper)、`product_backlog.md`(REQ-006)、本设计 + 交付记录 `docs/step5_2_rsu_frontend.md`。**不动根 index.html、不动后端/引擎、前端不算税**。分支 `feature/step5_2-rsu-frontend`,PR 到 main,CI 绿。
- **Claude**:本设计;实现后 headless 复现 RSU 调用 + 核对返回值 + 查前端无 RSU 税额计算残留(旧 calcRSU 的 `(futureValue-opt)*0.20` 必须删) + 根 hash 未变。
- **Shaw**:合并 PR。

## 8. 退出门槛
- [ ] RSU 面板完全由 `/calc/rsu` 返回(归属普通收入 + 所得税 + 可选卖出对比),带法条 + assumptions。
- [ ] 前端不再有 RSU 税额计算(旧 calcRSU 假算逻辑移除);涨幅滑块/期权字段移除。
- [ ] api.js 加 rsu helper;错误/不可用沿用统一处理。
- [ ] REQ-006 记入 backlog。
- [ ] CI 全绿;根 index.html hash 未变。
- [ ] Claude review 通过([Blocker]/[Major]/[Minor])。

## 9. 范围外
期权模块(REQ-006)、RSU 的 83(b)/AMT、other_taxable_income 自动带入(待 REQ-001)、FICA 在 RSU 面板合并显示(归属的 FICA 仍走 fica_tax)、FEIE/自雇/加密/Nexus 模块(后续逐个接)。
