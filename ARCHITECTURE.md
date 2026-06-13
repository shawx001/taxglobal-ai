# ARCHITECTURE — TaxGlobal AI 抗压边界（供多智能体审查的真实工业级背景）

> 用途：审查（`docs/code_review_matrix.md`）前先读本文件，按"真实当前架构"评估，**不为尚不存在的组件臆造风险**；同时以"生产目标架构"做前瞻性抗压评估。本文件随系统演进更新。

## 0. 业务画像与存在性约束（决定审查权重）
- **业务**：US-first 个人/SMB 报税计算与合规 SaaS（联邦 + 州；W-2/RSU/自雇/资本利得/加密/海外/电商 Nexus）。
- **数值即法律/财务风险**：算错一分 = 用户报错税 = 法律与赔付风险。→ **#1 审查焦点永远是数值精确到分 + 公式/阈值只来自版本化数据、可溯官方源(IRS Rev.Proc./州 DOR)**。这是本系统的核心 SLO，不是"功能跑通"。
- **极敏 PII**：SSN、收入、家庭、海外账户、券商/交易所数据。→ 安全与合规是工业级红线（加密传输/存储、最小权限、审计日志、数据驻留）。
- **外部 LLM 语言层 + 计算驻留（2026-06-08 Shaw 决策，M3 已落地，见 `docs/llm_integration_reference.md` + §2.7）**：Copilot 语言层（意图分类 + 自然语言表达 + 多轮 + W-2 vision）调用外部 LLM API（DeepSeek 默认，OpenAI 备选；vision 用 OpenAI 兼容 vision），**调用前经 PII sanitizer 脱敏**（SSN/姓名/邮箱掩码）。**税务计算与金额 100% 留在本地规则引擎、绝不经过 LLM**；涉及金额的回答必须来自规则引擎、可回链法条；Fact-checker 逐分核查 LLM 未篡改引擎数字（篡改 fail-closed）；`ENABLE_LLM=false`（默认）时降级为关键词分类 + 模板响应。**vision 数据驻留**：GPT-4o 在美国，真实 W-2（含 SSN）会出境；境内合规可切 SiliconFlow（改 `TAXGLOBAL_VISION_*`）。
- **强季节性(关键负载特征)**：年负载约 80% 集中在 1–4 月；**截止日尖峰**(4/15 报税、10/15 延期、季度预缴 4/6/9/1 月 15 日)是定义性负载事件。→ 抗压设计必须按"尖峰"而非"日均"。

## 1. 负载与 SLO 目标（上线前为目标值，Shaw 可校准）
- **QPS**：日常稳态 ~数百；**税季峰值目标 ~5,000 QPS**，截止日突发可冲更高 → 必须可水平扩展 + 过载降级。
- **延迟**：计算 API（纯 CPU）p99 目标 < 150ms；Copilot/LLM 答复属异步流式、SLO 另算。
- **正确性 SLO**：金额到分零容差 + 每个数可溯官方源 + golden 回归不可回退。
- **可用性**：税季截止窗口按高可用对待(冗余 + 自动扩缩 + 熔断降级)。

## 2. 当前架构（M2 + M3 + Phase C 完成，**现在真实存在**——当前 PR 审查以此为边界）

> M3（对话式 AI + W-2 识别 + 检索增强，PR #66–#81，2026-06-13）已合并。LLM/vision 等外部能力**默认关闭**（`ENABLE_LLM`/无 `VISION_MODEL`），关闭时行为与 M2 完全一致、`/calc/*` 不受影响；下文标注每项的 feature flag 与降级行为。

### 2.1 API 层
- **FastAPI**，**无状态**请求处理；CORS 白名单（`TAXGLOBAL_CORS_ORIGINS` 或 dev 默认）；`X-Admin-Token` HMAC 认证（审计管理端点）。
- **中间件栈**（外→内）：RequestIdMiddleware（request_id + 结构化 JSON 日志）→ AuditMiddleware（ASGI 级，异步 fire-and-forget 审计写入）→ CORSMiddleware → RateLimitMiddleware（M3.8，innermost：429 仍带 request_id + CORS 头，且在进入昂贵 LLM 调用前拦截；默认关 `TAXGLOBAL_ENABLE_RATE_LIMIT`）。
- **端点**：
  - `/calc/*`（8 个计算端点，M1 纯引擎，无外部依赖）
  - `/api/skills`（列出）/ `/api/skills/{name}`（调用 5 个 LangChain Skill；`extract_w2` 注册但 `expose_via_api=False`，不走通用路由）
  - `/api/assistant/query`（LangGraph 编排器入口：意图分类→Skill/KB路由→Guardrail→响应组装）+ `/api/assistant/stream`（M3.5 SSE 流式 Copilot：pipeline 含 fact-check 完成后再流式，绝不转发未核查 token）
  - `/api/documents/extract-w2`（M3.6 W-2 拍照/PDF 识别，vision；图片不存/不审计/不入日志）
  - `/api/knowledge/search`（GraphRAG 混合检索：Chroma 向量 → cross-encoder 重排(C.1) → CRAG 判级(C.2) → Neo4j 图查询 + 同主题多跳(C.3)）
  - `/api/profiles`（档案 CRUD，PostgreSQL，幂等 upsert）
  - `/api/tips`（KB 驱动个性化税务提醒 + 截止日）
  - `/api/admin/audit`（审计日志查询 + 哈希链验证，需 admin token）+ `/api/admin/llm-usage`（M3.7 LLM 用量/成本统计，需 admin token）
  - `/api/states`（51 jurisdictions 动态列表）、`/api/health`（含 chroma/embedder/reranker/llm/neo4j/pg 状态）

### 2.2 计算引擎（M1，不变）
- 纯函数 + Decimal（模块化 `engine/` 包：money/brackets/payroll/qbi/feie/state/crypto/rsu/nexus/summary + 门面）。
- **无共享可变状态** → 天然水平扩展。
- 规则数据：版本化 JSON `data/tax_years/YYYY/`（2025+2026），`@lru_cache` + `MappingProxyType` 冻结缓存；**热路径无磁盘/网络 IO**。

### 2.3 Agent + 知识层（M2 新增）
- **LangChain Skill 框架**（`backend/skills/`）：5 个引擎 Skill（income_tax / feie / rsu / crypto / nexus），LangChain `BaseTool` 接口，统一注册表。
- **LangGraph Workflow 编排器**（`backend/orchestrator/`）：确定性状态机（意图分类→Skill/KB路由→Guardrail检查→响应组装）。**M3 已升级**：意图分类 LLM 优先(`llm_classify_intent`)+关键词回退；响应生成 LLM 表达(`response.py` 场景化 prompt)+模板回退；多轮记忆(查询改写 `rewrite.py`)+ LLM 参数抽取(`extraction.py`)；金额问题无金额时出税率概览(`engine/overview.py`，纯规则数据)。
- **Guardrail 中间件**（`backend/guardrail/`）：金额来源验证（必须出自规则引擎）+ schema 校验 + 4 级升级（INFO/WARNING/NEEDS_REVIEW/BLOCKED）+ PII 检测。
- **GraphRAG 检索**（`backend/knowledge/`）：Neo4j 知识图谱（TaxRule/Jurisdiction/Topic/Source/Deadline 5 类节点 + 6 种关系）+ Chroma 向量库（`BAAI/bge-small-zh-v1.5` 本地 embedding）→ 混合检索（α×向量分 + β×图分）。
- **KB 驱动提醒**（`backend/knowledge/tips.py`）：根据档案（州/收入类型/报税身份）从知识图谱匹配个性化税务提醒 + 截止日排序。

### 2.4 存储层（M2 新增，全部可选——关闭后 /calc/* 不受影响）
- **PostgreSQL**（`backend/database.py`）：用户档案 `profiles` + 审计日志 `audit_log`；SQLAlchemy 2.0 async + Alembic 迁移；feature flag `ENABLE_POSTGRES`。
- **Neo4j**（`backend/knowledge/neo4j_client.py`）：税法知识图谱；driver 单例；feature flag `ENABLE_NEO4J`。
- **Chroma**（`backend/knowledge/vector_store.py`）：语义向量检索；本地持久化 `data/chroma/`；feature flag `ENABLE_CHROMA`。
- **Embedding**（`backend/knowledge/embedder.py`）：`sentence-transformers` 本地推理，CPU 可跑，数据不出境。

### 2.5 审计与合规（M2 新增）
- **审计日志**（`backend/audit/`）：ASGI 中间件自动捕获 Skill/Assistant/Tips/Admin 请求响应；异步写入 PostgreSQL；SHA-256 哈希链防篡改（`pg_advisory_xact_lock` 序列化）。
- **PII 脱敏**（`backend/audit/sanitizer.py`）：SSN→`***-**-1234`（含整数/无横杠/已掩码幂等处理）；姓名/邮箱/银行/密码→`[redacted]`；收入金额保留（审计需要）。
- **Admin 认证**：`TAXGLOBAL_ADMIN_AUDIT_TOKEN` 环境变量 + `X-Admin-Token` 请求头 + `hmac.compare_digest` 时间安全比较。

### 2.6 前端（M1 原型 + M3 聊天/上传）
- vanilla SPA 原型（`frontend/index.html` + `api.js`）；profile 暂仍 localStorage。
- **M3 新增**：`copilot.js`（SSE 聊天传输层，对接 `/api/assistant/stream`，**所有动态文本 HTML 转义**，多轮历史随请求发给后端做查询改写）；`w2-upload.js`（W-2/PDF 真实上传，对接 `/api/documents/extract-w2`，识别结果用户确认后填入计算器）。

### 2.7 LLM 语言层 + 多模态 + 检索增强（M3 + Phase C 新增，**默认关闭、降级安全**）
- **LLM Provider**（`backend/llm/`）：OpenAI 兼容接口（DeepSeek 默认，OpenAI 备选），`SanitizedProvider` 装饰器**外发前 PII 脱敏**（SSN/email），`TrackedProvider` 记录用量/成本。`ENABLE_LLM` 默认 **false** → 编排器走 M2 关键词+模板路径，零行为变化。
- **Fact-checker**（`backend/guardrail/fact_checker.py`）：LLM 生成的 `answer_text` 里每个金额（$/中文/k/USD 格式）经 Decimal 逐分核查与引擎输出比对；**篡改/幻觉 fail-closed**（丢弃 LLM 文本、保留结构化引擎答案）；一次反馈重试后仍失败则丢弃。结构化 `answer`（引擎数字）永不被 LLM 触碰。
- **Vision / W-2 识别**（`backend/llm/vision.py`）：OpenAI 兼容 vision（GPT-4o 已验证），独立 `TAXGLOBAL_VISION_*` 凭证；PDF 经 `pypdfium2` 渲染首页；**全防御解析**（金额 ROUND_HALF_UP、SSN 结构性不可提取）；**图片不存盘/不入审计/不入日志**（三重防泄漏）。无 `VISION_MODEL` → 503 未配置。
- **检索增强**（`backend/knowledge/`）：C.1 cross-encoder 重排（`reranker.py`，`bge-reranker-base`，召回池→精排→top_k；模型缺失降级向量序）；C.2 CRAG 纠错（`crag.py`，重排分判级，低相关→剔除+`confidence=low` 驱动诚实兜底；仅 reranked 时激活）；C.3 Neo4j 同主题多跳（`graph_search`，确定性 LIMIT）。

### 2.8 当前真实攻击面
- 请求体/参数畸形（已 422/invalid_input）、请求体大小、CORS 配置。
- M2：PG SQL 注入（SQLAlchemy 参数化防御）、admin token 泄露、审计日志 PII 泄露（sanitizer 防御）。
- **M3 新增**：外部 LLM/vision API 调用（PII 脱敏后 + 数据出境考量，见 §5）；prompt 注入（LLM 输出经 fact-check + 前端转义，不参与计算）；LLM 成本滥刷（限流 + 用量统计，默认关需生产开）；W-2 图片 PII（不存/不审计/不日志）；vision 数据驻留（OpenAI 在美国 → 真实 W-2 出境，可切境内 SiliconFlow）。

## 3. 生产目标架构（剩余 M4–M5，**计划中**——前瞻审查 + 解锁矩阵全项）
- **✅ 已交付（M3 + Phase C，移入 §2.7/2.8）**：Copilot LLM 语言层（意图分类 + 自然语言表达 + 多轮 + W-2 vision）、Fact-checker、检索增强（重排/CRAG/多跳）、SSE 流式、限流、用量统计。计算与金额仍 100% 本地规则引擎、不经 LLM。
- **范围分歧（诚实记录）**：计划书原 M3 还含 ① Google/Apple/微信 OAuth + Shopify/Amazon 电商 Nexus 真连；② **自训 Copilot 模型**。两者**未做**——实际语言层用外部 LLM（非自训），连接器推迟。归入 M4。
- **M4 训练闭环 + 连接器（计划中）**：Trace 回流 + LoRA 微调 + Eval Harness（自训模型）；OAuth + Shopify/Amazon 真连 → 需超时/重试风暴控制/熔断降级/限流，对外依赖故障不得拖垮核心计算链路。
- **M5 合规上线（计划中）**：前端 Next.js 14 + Tailwind、WebSocket 流式；PII 列级加密、HTTPS、生产部署（含开启限流 + vision 数据驻留决策）、安全审计。

## 4. 外部依赖
- **当前（M2+M3，全部可选——关闭后核心计算不受影响）**：PostgreSQL（档案+审计）、Neo4j（知识图谱 + C.3 多跳）、Chroma（向量库，本地文件）、sentence-transformers（本地 embedding + `bge-reranker-base` 重排，本地推理）、**外部 LLM API**（DeepSeek/OpenAI 兼容，PII 脱敏后调用，`ENABLE_LLM` 默认关）、**外部 vision API**（OpenAI 兼容，无 `VISION_MODEL` 则关）。本地模型（embedding/reranker）需预缓存（`local_files_only`，缺则降级）。
- **目标（M4+）**：自训 Copilot 模型（LoRA）、OAuth 提供方、Shopify/Amazon API。每项落地时本文件更新 + 审查矩阵安全/性能/SRE 全项对其生效。

## 5. 跨切面工业级约束（审查恒查）
- **PII 安全**：SSN/收入等传输+存储加密、最小权限、审计可追溯;日志/错误信息**不得泄露 PII**。
- **数据驻留 + LLM 边界**：税务计算与金额 100% 本地规则引擎、绝不经过 LLM；Copilot 语言层调用外部 LLM API 前必须经 PII sanitizer 脱敏；Guardrail 验证 LLM 未篡改引擎数字。
- **Guardrail**：涉及金额必出自规则引擎,模型不得编造数字;结论可回链法条。
- **幂等**：M2+ 的写入/摄取/外部调用须幂等(重试/重复提交不重复计、不损坏)。
- **可观测性**：M2+ 关键分支补 metrics + Error 日志,出事 1 分钟内可定位。

## 6. 审查含义（与 `docs/code_review_matrix.md` 配套）
- 按 §2 当前真实组件裁剪适用风险;§3 目标架构落地后再解锁对应安全/性能/SRE 全项。
- **当前每个 PR 必做**：数值精确到分(自建独立参考逐分核,不只对引擎自身)+ 输入健壮性 + 纯无状态可扩展 + PII/日志不泄露;矩阵其余项按存在性裁剪。
