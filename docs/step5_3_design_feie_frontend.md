# Step 5.3 设计文档 — FEIE 面板接后端 `/calc/feie`

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：Step 2 `feie_estimate`、Step 4 API、Step 5 前端模式、`coding_standards.md`、REQ-004
分支：`feature/step5_3-feie-frontend`
角色：Claude 出设计；Codex 实现。

> 目标：把 FEIE 面板从前端假算迁到 `/calc/feie`,显示后端真实的"330 天测试 / 豁免额 / 剩余应税" + 法条。**清掉三处假数**:硬编码 $130k 上限、单独算的(错的)"美国剩余税额"、硬编码的"当地税"。只动 FEIE 面板 + api.js;不动根 index.html、不动后端/引擎、前端不算税。

---

## 1. 现状(前端假算,要替掉)
`calcFEIE` 现在本地:`limit=130000`(硬编码)、`excluded=min(income,limit)`、`usTaxOnRemaining=bracketTax(remaining-15000, FED.single)`(**孤立、只按 single、忽略其他收入叠加 → 错**)、`localNote={pt:'葡萄牙 NHR 20%',...}`(**硬编码的假外国税**)。

## 2. 后端契约
`POST /calc/feie {foreign_earned_income, days_abroad}` → `result{qualifies_physical_presence_test, excluded_income, remaining_income}` + citations + assumptions。后端**只算美国 FEIE 豁免**,不算"剩余的美国税",也不算外国当地税。

## 3. 改动
- **api.js**:加 `feie: function(p){ return postCalc("/calc/feie", p); }`。
- **calcFEIE**:收集 `feie-income`→foreign_earned_income、`feie-days`→days_abroad → 调 `/calc/feie` → 用 `escapeHtml` 展示:330 天是否通过、豁免额、剩余应税、citations、assumptions。删除本地 `limit/excluded/usTaxOnRemaining` 计算。
- **删除"美国剩余税额"那行**(孤立假算):改为一句说明——"剩余 $X 仍是美国应税收入;请在『普通收入』模块连同其他收入一起算总税(叠加后税率才准)。"(不给孤立/会误导的数字。)
- **删除"当地税(葡萄牙 NHR 20%…)"**与 `feie-country` 选择器(硬编码假外国税)。外国当地税/协定/FTC 属后续独立模块(REQ-004 相邻),本面板不伪装。
- **保留** Step 5.1 已加的诚实说明(FEIE 只适用于海外劳动/服务赚取收入;被动收入走 FTC/被动模块)。
- 错误:后端不可用 → "服务不可用";422(如天数非法)→ 显示后端 message。

## 4. 设计决策
- **FEIE-1** 豁免逻辑全部来自 `/calc/feie`(上限/天数/豁免额不再前端硬编码)。
- **FEIE-2** 不在面板算"剩余的美国税"(需其他收入+申报身份叠加才准);只提示去普通收入模块合并算。后续 REQ-001 收入分桶后,海外剩余自动并入美国应税。
- **FEIE-3** 删除硬编码外国当地税 + 国家选择器(假数);外国税/协定/FTC 留后续模块。
- **FEIE-4** 复用 escapeHtml + api.js 错误处理;前端不算税。

## 5. 验收(诚实标注边界)
- headless 复现面板调用:`/calc/feie {foreign_earned_income:140000, days_abroad:340}` → qualifies true、excluded 130000.00、remaining 10000.00 + citations + assumptions。
- 边界:days 329 → 不通过、excluded 0、remaining=全额(后端已验)。
- 前端无 JS 自动化框架,代码评审 + 手动为主。
- 全套 unittest/ruff/pip-audit/数据校验 全绿;根 index.html hash 未变。
- grep 确认 FEIE 面板不再有 `limit=130000` / `usTaxOnRemaining` / 硬编码 `localNote` 外国税。

## 6. 交付物与分工
- **Codex**:`frontend/index.html`(calcFEIE 改调 `/calc/feie` + escapeHtml 展示;删本地豁免计算、删"美国剩余税额"行、删国家选择器+假当地税)、`frontend/api.js`(加 feie helper)、本设计 + 交付记录 `docs/step5_3_feie_frontend.md`。**不动根 index.html、不动后端/引擎、前端不算税**。分支 `feature/step5_3-feie-frontend`,PR 到 main,CI 绿。
- **Claude**:本设计;实现后 headless 复现 FEIE 调用 + 核对 qualifies/excluded/remaining + 查前端无 FEIE 假算残留(`limit=130000`、`usTaxOnRemaining`、`localNote` 必须删) + 根 hash 未变。
- **Shaw**:合并 PR。

## 7. 退出门槛
- [ ] FEIE 面板完全由 `/calc/feie` 返回(330天/豁免额/剩余 + 法条 + assumptions)。
- [ ] 前端不再有 FEIE 假算(硬编码上限、孤立美国税、硬编码外国税全删)。
- [ ] api.js 加 feie helper;错误/不可用沿用统一处理。
- [ ] CI 全绿;根 index.html hash 未变。
- [ ] Claude review 通过([Blocker]/[Major]/[Minor])。

## 8. 范围外
外国当地税/税收协定/FTC/被动收入(REQ-004,独立模块)、海外剩余自动并入美国应税(待 REQ-001)、自雇/加密/Nexus 模块(后续逐个接)。
