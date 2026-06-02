# Step 5.1 设计文档 — 前端/后端 Hardening + Backlog 记录

日期：2026-06-02
阶段：PLM 阶段 2（Design，小型 hardening）
依据：Step 5 交付、`coding_standards.md`、`code_review_checklist.md`
分支：`feature/step5_1-hardening`（从最新 main，**Step 1.2 合并后**切）
角色：Claude 出设计；Codex 实现。

> 目标：修 Step 5 暴露的三处前端/后端健壮性问题(escape / invalid JSON / CORS gate),并把"删除前端遗留 `caStateTax`/`nyStateTax`"记进 backlog。**本步只记录、不删除旧州税函数**(它们仍被未迁移模块使用,贸然删会破坏原型展示)。不动根 `index.html`、不动税务计算逻辑。

---

## A. 前端输出转义（escape）
现状:`frontend/index.html` 把后端返回文本未转义插入 DOM:
- L1183 citations:`c.citation` 进 `title="..."`、`c.source_id` 进文本
- L1196 `options.reason`(not_covered 原因)进 innerHTML

改法:
- 新增 `escapeHtml(value)`,转义 `& < > " '`。
- 对**所有 API 来源字符串**(citation、source_id、reason、assumptions 文本、breakdown 里来自后端的字段)在进 innerHTML / 属性前 escape。
- 本地 UI 文案(`taxText` 常量)可信,无需强制 escape。
- 目的:后端/未来 Copilot/知识库返回的文本永远不能破坏 HTML 或注入。当前数据自控、风险低,但属应有的输出编码卫生 + 为 Step 8 铺路。

## B. api.js 对 2xx 但无效/空 JSON 的兜底
现状:`response.json().catch(()=>null)` → 若 200 但 body 为 null 或缺字段,`calcTax` 访问 `body.result.tax` 会抛未捕获错误。
改法:解析后,若 `response.ok` 且 (`body` 为 null 或 `body.status` 未定义) → 抛 `ApiError("Server returned an unexpected response.", code:"invalid_response")`,让 `calcTax` 的错误分支显示清晰提示,而非崩溃。保留现有 `service_unavailable`(网络)与 `request_failed`(非 2xx)处理。

## C. 后端 CORS gate（`backend/main.py`）
现状:硬编码 dev 列表,含 `"null"` 源、`allow_headers=["*"]`,无开关。
改法(仍 dev 友好,但可控、可收紧):
- 允许源改为**读环境变量** `TAXGLOBAL_CORS_ORIGINS`(逗号分隔);未设置时回退到默认 localhost 列表(保持本地开发体验)。
- 默认列表**移除 `"null"`**(前端经 `http://127.0.0.1:5173` 提供,不需要 file:// 的 null 源;若确需可经环境变量加)。
- `allow_headers` 从 `["*"]` 收紧为 `["Content-Type"]`(我们只发 JSON)。
- `allow_methods` 保持 `["GET","POST","OPTIONS"]`。
- 注释 + 交付记录写明:默认 dev;生产用 `TAXGLOBAL_CORS_ORIGINS` 显式指定。

## D. Backlog 记录（加入 `product_backlog.md`，本步只记不删）
新增一行(沿用现有表格式):

```
| REQ-003 | 删除前端遗留 caStateTax/nyStateTax，州税一律走后端 | 迁移自雇/W-2/6国对比模块到后端时 | 🟢 | frontend/index.html 仍有硬编码 caStateTax/nyStateTax（NY 税率已过时 5.85%/6.25%，与官方 5.5%/6% 不符），被未迁移模块（自雇 ~L1442、L1561、usTaxTotal 6国对比）使用。**约束：新模块一律不得使用前端州税函数，州税只调 /calc/state-income；迁移上述模块到后端时一并删除旧函数。本步不删，避免破坏未迁移模块原型展示。** |
```

## 测试与验收（诚实标注边界）
- **CORS**(可自动化):后端测试断言——允许源(`http://127.0.0.1:5173`)拿到 `Access-Control-Allow-Origin`;**非允许源**(如 `http://evil.example`)**不**返回 ACAO(负向)。
- **前端 escape / invalid JSON**:无 JS 自动化框架,以**代码评审 + 手动**为主;Claude review 会读 `escapeHtml` 应用点 + 构造一个含 `<`/`"` 的 reason 看是否被转义(可临时让 state-income 返回带特殊字符的 reason,或在 review 时静态确认)。JS 测试框架仍列为后续基建。
- 全套:`unittest discover` / `ruff` / `pip-audit` / 数据校验 全绿。
- 根 `index.html` SHA256 仍 `833508…4b69`(本步只改 `frontend/index.html` 副本与后端)。

## 交付物与分工
- **Codex**:`backend/main.py`(CORS env gate)、`tests/test_api_calc.py`(CORS 允许+拒绝两条)、`frontend/api.js`(invalid_response 兜底)、`frontend/index.html`(escapeHtml + 应用到 API 文本)、`product_backlog.md`(加 REQ-003)、本设计文档 + 交付记录 `docs/step5_1_hardening.md`。**不删 caStateTax/nyStateTax、不动根 index.html、不动税务逻辑**。分支 `feature/step5_1-hardening`,PR 到 main,CI 绿。
- **Claude**:本设计;实现后评审 + 验证(CORS 允许/拒绝、escape 应用点、invalid JSON 兜底、根 hash 未变)。
- **Shaw**:合并 PR。

## 退出门槛
- [ ] API 文本(citation/reason/assumptions)经 escape 后插 DOM;构造特殊字符不破坏渲染。
- [ ] api.js 对 2xx 空/无效 body 返回清晰错误,不崩。
- [ ] CORS 源可经 `TAXGLOBAL_CORS_ORIGINS` 配置,默认去掉 `null`、headers 收紧;允许/拒绝两条测试通过。
- [ ] `product_backlog.md` 新增 REQ-003;旧州税函数**未删**。
- [ ] ruff + unittest + pip-audit + 数据校验 CI 全绿;根 `index.html` hash 未变。
- [ ] Claude review 通过([Blocker]/[Major]/[Minor])。

## 范围外
真正删除 `caStateTax`/`nyStateTax`(等迁移对应模块)、其余模块接后端、生产级 CORS 细化、前端 JS 自动化测试框架。
