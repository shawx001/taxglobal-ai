# 项目交接 / 上下文摘要（给新对话快速接手）

最后更新：2026-06-13（M1+M2+M3+Phase C 全部合并；角色与流程已演进，见 §1/§3）
用途：换新对话时，先读本文件 + `feature_status.md` + `roadmap_skills_status.md` + `product_backlog.md`，即可无缝接手。

---

## 1. 项目与角色
- **项目**：TaxGlobal AI —— AI 驱动的美国税务计算与合规平台(U.S.-first MVP)。核心卖点:**每个税额可追溯到法条、可审计、不伪装确定性**。
- **分工(已演进)**:
  - **默认**:**Claude(我)** 写 Codex prompt + 设计文档 + code review + 数值查证;**Codex** 写代码开 PR;Shaw 合并。
  - **2026-06 起 Shaw 多次授权我直接干**:自己写代码(M3.2–3.8、Phase C 全是我自实现)、本地 commit、`git push`、`gh pr merge`。授权是逐任务/逐授权累积的——M3 之后默认仍是 "Codex 写代码"(Shaw:"你以后写代码还是得让codex写啊"),但 Shaw 明确说"自己写"时我就自实现。
  - **流程铁律(2026-06-12 Shaw 批评后立的硬门禁)**:**`gh pr checks <n>` 全绿才能 `gh pr merge`**,绝不在 CI 红时合并。CI 含 pip-audit(新 CVE 会无代码变更地弄红 main)、ruff、unittest、数据校验。每 PR 请求 Copilot 粗审,有价值就修、无意义就回复理由跳过。
  - **Shaw(用户)**:拍板产品决策(LLM 选型、vision 供应商、是否充值等)。
- **最高原则**:**数值精确是第一要义**;不确定就明确标注、绝不给假数/假范围;税率/阈值只能来自 `data/`,引擎不裸写。**LLM 只做"耳朵+嘴"(理解+表达),所有税额来自规则引擎并经 fact-checker 逐分核查**。

## 2. 工作方法(必读文档)
- `docs/engineering_process.md` — 6 阶段流程 + 每步卡点
- `docs/coding_standards.md` — 写码规范
- `docs/code_review_checklist.md` — 我评审用的 5 维清单 + **标签 `[Blocker]/[Major]/[Minor]/[Nitpick]`**
- `docs/feature_status.md` — **实时功能状态总表(每步合并后我更新)**
- `docs/product_backlog.md` — 需求台账 REQ-001..011
- 每步:`docs/stepN_design_*.md`(设计) + `docs/stepN_*.md`(交付记录)

**我的 review 流程**:同步到 PR commit → 读代码 → **独立跑**(`python -m unittest discover -s tests`、`ruff check engine backend tests`、`pip-audit -r backend/requirements.txt`、`powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1`、`git diff --check`)→ **独立重算关键税额**(不信 PR 描述)→ 必要时 headless 复现 API/前端调用 → 按标签给结论。
- Python 解释器:`C:\Users\shawx\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`,`$env:PYTHONPATH=仓库根`。

## 3. 当前进度(main) — M1+M2+M3+Phase C 全部合并
**M1 引擎硬化**(2026-06-07 关闭):全 50 州+DC(51 jurisdictions)、REQ-009 三块合并计税、2026 税年、引擎模块化。
**M2 Agent+知识层**(2026-06-09 关闭,PR #45–#63):三库基建、知识图谱+入库、GraphRAG 检索、5 引擎 Skills、Guardrail、LangGraph 编排、提醒系统、审计日志、集成验收。
**M3 对话式 AI+W-2+检索增强**(2026-06-13,PR #66–#81,详见 `feature_status.md` §E + `m3_step_plan.md` + `phase_c_design.md`):
- M3.1–3.8:LLM Provider(OpenAI 兼容+PII 脱敏)、意图分类、自然语言响应、Fact-checker、Copilot 聊天 UI(SSE+多轮记忆+参数抽取)、W-2/PDF 识别(GPT-4o 真实文件 9/9 准)、Token 成本统计、限流。
- Phase C:C.1 cross-encoder 重排、C.2 CRAG 纠错、C.3 Neo4j 多跳。
- 640+ tests + ruff + CI 全绿。**OA 2065 知识 chunk 已灌进 Chroma**。
**范围分歧**:计划书 M3 原含 OAuth/Shopify/Amazon 连接器 + 自训 Copilot 模型 → **未做,归 M4**;实交付为外部 LLM 对话 + 识别 + 检索增强。

### 引擎函数(全 ✅,纯函数、Decimal、读 JSON、带 citations/assumptions)
bracket_tax, federal_income_tax, fica_tax, self_employment_tax, feie_estimate, state_income_tax(51 jurisdictions), nexus_estimate, crypto_gain_estimate(+州), rsu_tax_estimate, qbi_deduction, income_tax_summary(REQ-009 三块全合并)。新增 `engine/overview.py`(税率概览,供 chat 的 rates 问题,纯规则数据)。

### M3 新增后端模块
- `backend/llm/`:provider(OpenAI 兼容)、client(生命周期+TrackedProvider+SanitizedProvider 包装)、sanitize_pipeline(PII)、vision(W-2,OpenAI 兼容,PDF 首页 pypdfium2 渲染)、token_optimizer、usage_tracker。
- `backend/orchestrator/`:intent(关键词+LLM)、response(场景化 prompt)、rewrite(多轮查询改写)、extraction(LLM 参数抽取)、nodes(format_node 接 fact-check+CRAG confidence)、routes(`/api/assistant/query` + `/stream` SSE)。
- `backend/guardrail/fact_checker.py`(金额逐分核查)。`backend/knowledge/`:reranker(C.1)、crag(C.2)、search(重排+CRAG+多跳集成)。
- `backend/routes/documents.py`(`POST /api/documents/extract-w2`)。`backend/ratelimit.py`(M3.8)。
- `backend/audit/routes.py` 加 `GET /api/admin/llm-usage`(X-Admin-Token)。

### 配置(全部 env 可覆写,`backend/config.py`)
`ENABLE_LLM`(默认关)、`TAXGLOBAL_LLM_*`(provider/key/model/base_url)、`TAXGLOBAL_VISION_*`(独立 key/base_url/model)、`ENABLE_RERANK`/`RERANK_*`、`ENABLE_CRAG`/`CRAG_*`、`GRAPH_RELATED_LIMIT`、`TAXGLOBAL_ENABLE_RATE_LIMIT`(默认关,生产开)/`RATE_LIMIT_*`、`TAXGLOBAL_LLM_PRICE_*`。本地密钥走 `.claude/secrets.local.bat`(gitignored,launch.json call 它)。

### 后端 / 前端
- FastAPI:`/calc/*` + `/api/assistant/{query,stream}` + `/api/documents/extract-w2` + `/api/knowledge/search` + `/api/admin/{audit,llm-usage}` 等。`/health` 报 chroma/embedder/reranker/llm/neo4j/pg。
- 前端 `frontend/`:`index.html`(原型壳)、`api.js`、`copilot.js`(SSE 聊天传输层,全 HTML 转义)、`w2-upload.js`(真实上传)。**根 `index.html` 冻结 hash 仍是每步硬验收**。
- 前端聊天已接真后端(关键词/LLM 意图→引擎/KB→fact-check→SSE);W-2 页接真识别。
- 历史遗留(REQ-003):部分前端原型模块(6 国对比 calcTreaty 等)仍前端假算,非本阶段重点。

## 4. 关键税务结论(已查证,用于下游)
- **自雇交两层联邦税 + 州税**:① SE 税(§1401:SS 12.4%@176100 + Medicare 2.9% + 附加 0.9%);② 联邦所得税(净利润 − ½SE − QBI − 标准扣除);③ 州税。NIIT **不**适用积极自雇。详见 `docs/tax_rules_self_employment.md`。
- **QBI(§199A)**:20%,2025 阈值 197300单/394600 MFJ(QSS 归 All-Other=197300),上限 247300/494600;只减所得税不减 SE 税。
- **各州税基不同**(精确算州税的关键):CA/NY/GA 起点=联邦AGI − 州标准扣除(CA 5706/11412、NY 8000/16050/HOH11200、GA 12000/24000),均不认 QBI;IL=联邦AGI − 免税额2850/人;CO=联邦应税收入 + QBI加回。
- 资本利得 LTCG 2025:single 48350/533400、mfj 96700/600050 等;NIIT 3.8% 阈值 200k/250k/125k。

## 5. ⏭ 立即下一步(2026-06-13 待 Shaw 拍板方向)
M3 + Phase C 已交付。候选下一步:
1. **正式关账 M3**:更新 `ARCHITECTURE.md`(加 M3/Phase C 架构层),走 m3_step_plan 关闭标准。
2. **打通外部依赖看真实效果**:起 Neo4j(Docker)验 C.3 真实多跳;或确认 vision 供应商(OpenAI 数据出境 vs 境内 SiliconFlow)。
3. **M4**:训练闭环(Trace 回流 + LoRA + Eval Harness)+ 计划书原 M3 推迟的连接器(OAuth/Shopify/Amazon)。
4. **挂账清理**:见 §6 backlog + Phase 1 PR2/PR3 数据补全。

**未完成/受阻(非代码,等外部)**:W-2 vision 真实用需 vision key(OpenAI 已验证但出境美国);C.1/C.2 重排需 `bge-reranker-base` 缓存(本机已下,生产需同样缓存);C.3 真实多跳需 Neo4j 起服务;限流生产需开 `TAXGLOBAL_ENABLE_RATE_LIMIT=true`。

## 6. Backlog(`product_backlog.md`)
REQ-001 收入分美国/海外｜002 档案→计算同步｜003 删前端 caStateTax/nyStateTax｜004 海外被动收入/FTC｜005 档案模型重构(身份≠收入类型)｜006 股票期权 NQSO/ISO/ESPP｜008 QBI(✅已由 2.4 实现)｜009 income_tax_summary(=下一步)｜010 自雇健保/退休扣除+季度预缴｜011 州级残余税基一致性(1.4 已做核心,残余待补)。
**待补记**:REQ-007 确定性 crypto 税务优化器(HIFO/FIFO/LIFO 选最省 + 税损收割 + 持有期临界);仅税务优化,**非投资建议**(投资量化属受监管的另一产品,明确不做)。

## 7. 约定与踩过的坑
- **未提交的 docs 会被 Codex 流程清掉**:每个 Codex prompt 第 0 步都要"保留并提交未跟踪 docs";被清过一次(后从 stash 恢复)。
- **根 index.html hash 不变**是每步硬性验收。
- PowerShell(cp1252)对中文/emoji 输出会崩 → 探针脚本用 ASCII 或 `$env:PYTHONIOENCODING="utf-8"`。
- Chrome 扩展(Claude in Chrome)时好时坏 → 前端验证常用 **headless**(httpx 复现页面的 API 调用序列 + 读渲染函数字段)。
- 开发服务器要重启才加载新代码(踩过 stale uvicorn 把 tax_year→500 误判)。
- `.gitattributes`:`data/sources/**/raw/** -text -diff -eol`(保官方归档字节,跨平台 hash 稳定)。
- `requirements.txt` 只放运行时;测试依赖(httpx)在 `requirements-dev.txt`;`pip-audit` 是 CI 阻塞项。
- Codex 报 "gpt-image-2 不存在" = Codex 自身图像模型配置问题,**与本项目无关**,别理它。
- 商业化:网页上线只需 域名+托管+HTTPS(不必上 App Store);注册域名/开发者账号/付款/法律免责 = Shaw 自己做,我做不了。
- **CI 红绝不合并(2026-06-12 教训)**:merge 前必跑 `gh pr checks <n> --watch`;曾因没看 CI 合了 3 个 PR(pip-audit 撞新 CVE 弄红 main,与代码无关但仍是流程错)。新 CVE 无修复版时→单独 PR 文档化 `--ignore-vuln`。本地依赖要与 CI 对齐(曾因本地缺 tiktoken 致测试本地过 CI 挂)。
- **HF 模型下载这环境网络极不稳**:embedder/reranker 都是重试多次(`huggingface_hub.snapshot_download` 直连,有时连试 4 次才过)才下来;`local_files_only=True` 运行时只读缓存,缺则优雅降级。
- **vision 数据出境**:W-2 含 SSN,GPT-4o 在美国→真实用户数据出境;Shaw 在意"数据不出境"→可切境内 SiliconFlow(改 `TAXGLOBAL_VISION_*` 三个 env)。DeepSeek 官方 API 无视觉能力(2026-06-12 实测 image_url 被拒)。
- **密钥**:`.claude/secrets.local.bat`(gitignored)set 各 key;**绝不把真实 key 写进任何 git 跟踪文件**;聊天里出现过的 key 提醒 Shaw 轮换。
- **PowerShell here-string + native exe**:commit message 含 `(`/`)`/`+`/`<=` 等会被 PS 解析器当 pathspec 报错→用纯文本或先 `git add` 再 `git commit -m @'...'@`(避开这些符号)。
