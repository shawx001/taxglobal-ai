# REQ-002 设计文档 — 前端「合并计税总览」(档案 → 一次 income_tax_summary)

日期:2026-06-03
阶段:PLM 阶段 2(Design)/ 里程碑 M1 收尾
依据:`product_backlog.md` REQ-002;引擎 `income_tax_summary`(REQ-009 Block 1/2/3 已合并)、`backend/routes/calc.py` `/calc/income-summary`、`frontend/index.html` + `frontend/api.js`
分支:`feature/req002-frontend-overview`(基于 Block 3 合并后的 main)
角色:Claude 出设计 + 已验证黄金值;Codex 实现 + 开 PR;Shaw 拍板合并。
工程标准:见 `coding_standards.md` §六(复用 / 抗并发 / 防御性输入);两份 index.html 中**根 index.html 冻结不碰**,仅改 `frontend/index.html`。

> 目标:把现在「各模块孤立相加」(个税模块分别调 `/calc/federal-income` + `/calc/fica` + `/calc/state-income` 再在 JS 里相加,见 `frontend/index.html` 约 1296–1327)替换为**档案表单 → 一次 `/calc/income-summary` 调用 → 引擎返回的正确合并总税**。只有合并引擎才正确处理共享 SS wage base、合并 Additional Medicare、QBI、资本利得 QDCGT 叠加、NIIT、FEIE 税率叠加等跨收入交叉;孤立相加会算错。

---

## 0. 关键设计点
1. **唯一权威总税来自一次 `income_tax_summary` 调用**;前端不得再把多个 `/calc/*` 结果在 JS 里相加当总税。孤立的 federal/fica/state 三连调用(及其求和)在本块被该合并调用取代。
2. **复用现有 `TaxGlobalApi.incomeSummary`**(`api.js` 已有,打 `/calc/income-summary`),不新增 client 方法。
3. **展示引擎自己的 `breakdown` / `total_tax` / `citations` / `assumptions` / `status` / `reason`**——不在前端重算或臆造数字;`assumptions` 与 `not_covered`(如州未覆盖)必须如实显示(诚实第一)。
4. **RSU / crypto / nexus / FEIE 单模块保留**为单项 what-if(本块不合并它们);本块只处理「个税合并总览」这一总税入口。

## 1. 档案表单字段 → `income_tax_summary` 参数映射
表单(在 `frontend/index.html` 个税模块内扩展为档案总览)收集并映射(参数全为引擎已支持的 keyword 参数):

| 表单字段 | 引擎参数 | 说明 |
|---|---|---|
| 报税身份 | `filing_status` | 下拉,取值对齐引擎:`single / married_filing_jointly / married_filing_separately / head_of_household`(别名 mfj/mfs/hoh)。**不要硬编码税率,只是身份选项。** |
| 州(可选) | `state_code` | 两位州码;留空=不算州税 |
| W-2 工资 | `w2_wages` | |
| 自雇净利润 | `net_self_employment_profit` | |
| 其它普通收入 | `other_ordinary_income` | 利息/普通分红/短期外的普通收入 |
| 长期资本利得 | `long_term_capital_gain` | |
| 短期资本利得 | `short_term_capital_gain` | |
| 海外赚取收入 | `foreign_earned_income` | |
| 海外天数 | `days_abroad` | 整数 0..366(引擎拒绝非整数) |
| 税前 401k/退休 | `retirement_contributions` | above-the-line |
| 自雇健康保险 | `se_health_insurance` | above-the-line |
| 扣除方式 | `deduction` | 标准扣除=留空(引擎用标准);逐项=填金额 |
| (高级,可折叠) | `qbi_w2_wages` / `qbi_ubia` / `is_sstb` / `modified_agi` | 默认不填走缺省;高级用户可填 |

`tax_year` 固定 2025(与引擎默认一致)。

## 2. 单次调用与渲染
- 组装 payload(仅放用户填了的字段,见 §4 空 vs 0)→ `await TaxGlobalApi.incomeSummary(payload)`。
- `status === "ok"`:头部展示 `result.total_tax`(总税)+ 有效税率(total_tax / 总收入,总收入由各收入桶相加用于展示,**不参与计税**);逐行渲染 `result.breakdown`;展示 `result.citations`(法条/来源)与 `result.assumptions`(含未建模/简化提示)。
- `status === "invalid_input"`:展示 `reason`,不显示假总额。
- 州 `not_covered`:在州行如实标注「未覆盖」+ `reason`,**总税仍显示联邦+工资+NIIT 等已算部分**(引擎已如此返回),不静默归零误导。
- 单次请求用递增 `requestId` 防竞态(复用现有 `taxRequestSeq` 模式),后到响应丢弃。

## 3. 取代「孤立相加」
- 删除/改写个税模块里 `federalIncome + fica + stateIncome` 的三连调用与 `federalTax+ficaTax+stateTax` 求和(约 1296–1327),改为单次 `incomeSummary`。
- 原模块已有的输入(收入、州、401k、扣除方式/金额)平移进档案表单;新增自雇/资本利得/海外字段。
- 渲染从「自拼 federal/fica/state 三块 + 自算 total」改为「直接渲染引擎 breakdown + total_tax」。

## 4. 防御性输入(硬要求,我的 review 标准)
- **空 vs 0**:输入框留空 → 该字段**不放进 payload**(走引擎缺省 0/标准扣除);用户**显式输入 0** → 放 0。逐字段区分,别把空coerce成0导致语义错。
- **负数**:数值字段 `Math.max(0, value)` 夹零(后端 schema 也 ge=0,前端先挡,避免无谓 422)。
- **days_abroad**:整数;非整数/超 366 由后端 422 或引擎 invalid_input,前端如实显示错误,不静默改值。
- **每个 API 取值前判空**:`body.result?.total_tax` 等,响应缺字段不抛未捕获异常;`status !== "ok"` 走对应分支。
- **后端不可用**:`api.js` 已抛 `service_unavailable`,前端捕获并提示「后端未启动」。

## 5. 交互式联调页(Shaw 选定:可点击本地联调页)+ 自动化 integration test
**(a) 一条命令同起前后端的 dev 联调脚本**(如 `scripts/run_overview_dev.py`,或 README 文档化命令):
- 同时拉起:`uvicorn backend.main:app`(:8000)+ 静态服务 `frontend/`(放在 CORS 已放行的 `:5173`),并自动打开浏览器到总览页。
- **不得污染生产 `create_app()`**——dev 静态托管只在该脚本里,生产 app 保持纯净(stateless/pure 原则)。CORS 默认已放行 127.0.0.1:5173/8000,无需改后端。
- 进程退出时清理子进程。

**(b) 交互核对清单**(`docs/req002_overview_manual_checklist.md` 或联调页内嵌):列出下面 §6 的几组「输入 → 期望总税」,Shaw 在浏览器里照填、对数。

**(c) 自动化 integration test**(进 CI,锁前后端契约):
- 用 FastAPI `TestClient` 按**前端档案 payload 的形状**打 `/calc/income-summary`,断言 §6 各场景的 `total_tax` 与关键 `breakdown` 行项。
- 字段映射(表单 id → 引擎参数)用一张表文档化,test 与联调清单共用同一组场景值;JS 端真实拼包由(a)(b)人工点验覆盖(纯 vanilla 前端无 JS 测试框架,这是诚实的职责切分)。

## 6. 黄金核对场景(已逐分验证,联调清单 + 自动化 test 共用)
| 场景 | 输入 | 期望(2025, single) |
|---|---|---|
| A 工资+长期利得 | w2_wages 200000, long_term_capital_gain 50000 | total_tax **60465.20**(federal 37247 / LTCG 7500 / NIIT 1900 / payroll 13818.20) |
| B FEIE | foreign_earned_income 200000, days_abroad 330 | feie_excluded 130000, total_tax **13200.00** |
| C 全组合 | net_self_employment_profit 60000, long_term_capital_gain 40000, foreign_earned_income 100000, days_abroad 330 | qbi 8152.23, total_tax **19875.71** |
| D 自雇+州 | net_self_employment_profit 100000, state_code CA | total_tax **27311.11**(含 CA 州税) |

(以上均为引擎已合并、我已独立逐分核验的值。)

## 7. 诚实边界 / 冻结文件
- 本块只接「合并总税」入口;RSU/crypto/nexus 完整并入档案桶、州级 FEIE、FTC 等列后续 REQ。
- `assumptions` 必须原样透传展示(不裁剪未建模提示)。
- **根 `index.html` 冻结**:hash 不变;只改 `frontend/index.html`(+ 新增 dev 脚本/测试/文档)。

## 8. 验收(退出门槛)
- [ ] 个税模块改为**单次** `income_tax_summary` 调用;JS 内不再有 federal/fica/state 求和当总税。
- [ ] §6 四场景在联调页手填可得期望总税;自动化 integration test 四场景全绿。
- [ ] 防御性输入全覆盖(空 vs 0、负数夹零、days 非整、响应判空、后端不可用提示)。
- [ ] `assumptions` / `not_covered` / `invalid_input` 如实显示;无静默假数。
- [ ] dev 联调脚本一条命令同起前后端、自动开浏览器、退出清理;**不改 `create_app()`**。
- [ ] ruff + 后端 unittest + 新 integration test + `git diff --check` 全绿;**根 index.html hash 不变**;`frontend/index.html` 改动仅限本模块。
- [ ] Claude 逐行(5 维)review + 实跑联调页对四场景 + 跑 integration test 核对。

## 9. 交付物与分工
- **Codex**:`frontend/index.html`(个税模块→档案合并总览,单次调用 + breakdown/citations/assumptions 渲染 + 防御性输入);dev 联调脚本(`scripts/run_overview_dev.py`)+ 交互核对清单文档;`tests/`(自动化 integration test,四场景);设计(本文件)+ 交付记录 `docs/req002_frontend_overview.md`;更新 `feature_status.md` / `product_backlog.md`(REQ-002 完成,M1 收尾)/ `roadmap_skills_status.md`(parse_profile→可用)。分支 `feature/req002-frontend-overview`,PR→main,CI 绿。
- **Claude**:本设计 + 已验证黄金值;实现后逐行 review + 实跑联调 + integration test 核对。
- **Shaw**:在联调页点验、拍板合并。
