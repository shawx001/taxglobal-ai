# ARCHITECTURE — TaxGlobal AI 抗压边界（供多智能体审查的真实工业级背景）

> 用途：审查（`docs/code_review_matrix.md`）前先读本文件，按"真实当前架构"评估，**不为尚不存在的组件臆造风险**；同时以"生产目标架构"做前瞻性抗压评估。本文件随系统演进更新。

## 0. 业务画像与存在性约束（决定审查权重）
- **业务**：US-first 个人/SMB 报税计算与合规 SaaS（联邦 + 州；W-2/RSU/自雇/资本利得/加密/海外/电商 Nexus）。
- **数值即法律/财务风险**：算错一分 = 用户报错税 = 法律与赔付风险。→ **#1 审查焦点永远是数值精确到分 + 公式/阈值只来自版本化数据、可溯官方源(IRS Rev.Proc./州 DOR)**。这是本系统的核心 SLO，不是"功能跑通"。
- **极敏 PII**：SSN、收入、家庭、海外账户、券商/交易所数据。→ 安全与合规是工业级红线（加密传输/存储、最小权限、审计日志、数据驻留）。
- **数据驻留/不出境**：合规要求 + 计划约束——**Copilot 由自部署微调模型驱动，不接任何第三方 LLM API**；涉及金额的回答必须来自规则引擎(guardrail)，可回链法条。
- **强季节性(关键负载特征)**：年负载约 80% 集中在 1–4 月；**截止日尖峰**(4/15 报税、10/15 延期、季度预缴 4/6/9/1 月 15 日)是定义性负载事件。→ 抗压设计必须按"尖峰"而非"日均"。

## 1. 负载与 SLO 目标（上线前为目标值，Shaw 可校准）
- **QPS**：日常稳态 ~数百；**税季峰值目标 ~5,000 QPS**，截止日突发可冲更高 → 必须可水平扩展 + 过载降级。
- **延迟**：计算 API（纯 CPU）p99 目标 < 150ms；Copilot/LLM 答复属异步流式、SLO 另算。
- **正确性 SLO**：金额到分零容差 + 每个数可溯官方源 + golden 回归不可回退。
- **可用性**：税季截止窗口按高可用对待(冗余 + 自动扩缩 + 熔断降级)。

## 2. 当前架构（M2 完成，**现在真实存在**——当前 PR 审查以此为边界）

### 2.1 API 层
- **FastAPI**，**无状态**请求处理；CORS 白名单（`TAXGLOBAL_CORS_ORIGINS` 或 dev 默认）；`X-Admin-Token` HMAC 认证（审计管理端点）。
- **中间件栈**：RequestIdMiddleware（request_id + 结构化 JSON 日志）→ AuditMiddleware（ASGI 级，异步 fire-and-forget 审计写入）→ CORSMiddleware。
- **端点**：
  - `/calc/*`（8 个计算端点，M1 纯引擎，无外部依赖）
  - `/api/skills`（列出）/ `/api/skills/{name}`（调用 5 个 LangChain Skill）
  - `/api/assistant/query`（LangGraph 编排器入口：意图分类→Skill/KB路由→Guardrail→响应组装）
  - `/api/knowledge/search`（GraphRAG 混合检索：Neo4j 图查询 + Chroma 向量语义搜索）
  - `/api/profiles`（档案 CRUD，PostgreSQL，幂等 upsert）
  - `/api/tips`（KB 驱动个性化税务提醒 + 截止日）
  - `/api/admin/audit`（审计日志查询 + 哈希链验证，需 admin token）
  - `/api/states`（51 jurisdictions 动态列表）、`/api/health`（含三库连接状态）

### 2.2 计算引擎（M1，不变）
- 纯函数 + Decimal（模块化 `engine/` 包：money/brackets/payroll/qbi/feie/state/crypto/rsu/nexus/summary + 门面）。
- **无共享可变状态** → 天然水平扩展。
- 规则数据：版本化 JSON `data/tax_years/YYYY/`（2025+2026），`@lru_cache` + `MappingProxyType` 冻结缓存；**热路径无磁盘/网络 IO**。

### 2.3 Agent + 知识层（M2 新增）
- **LangChain Skill 框架**（`backend/skills/`）：5 个引擎 Skill（income_tax / feie / rsu / crypto / nexus），LangChain `BaseTool` 接口，统一注册表。
- **LangGraph Workflow 编排器**（`backend/orchestrator/`）：确定性状态机（关键词意图分类→Skill/KB路由→Guardrail检查→响应组装）。M3 升级为 Qwen 模型分类。
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

### 2.6 前端（M1，不变）
- vanilla SPA 原型（`frontend/index.html` + `api.js`）；profile 暂仍 localStorage（M3 接服务端档案）。

### 2.7 当前真实攻击面
- 请求体/参数畸形（已 422/invalid_input）、请求体大小、CORS 配置。
- M2 新增：PG SQL 注入（SQLAlchemy 参数化查询防御）、admin token 泄露、审计日志 PII 泄露（sanitizer 防御）。
- **当前无**：Redis/缓存、消息队列、外部 API 调用、LLM。

## 3. 生产目标架构（M3–M5，**计划中**——前瞻审查 + 解锁矩阵全项）
- 前端 Next.js 14 + Tailwind；API FastAPI + WebSocket(流式 Copilot)。
- **M3 模型层**：自部署 Qwen 基座 + LoRA + vLLM(热加载 adapter)；Qwen-VL 做 W-2 OCR。**全部自部署,数据不出境。** 编排器意图分类从关键词匹配升级为模型分类。
- **M3 连接器**：Google/Apple/微信 OAuth；Shopify/Amazon(电商 Nexus 真连)。→ 需超时/重试风暴控制/熔断降级/限流;对外依赖故障不得拖垮核心计算链路。
- **M4 训练闭环**：Trace 回流 + LoRA 微调 + Eval Harness。
- **M5 合规上线**：PII 列级加密、HTTPS、生产部署、安全审计。

## 4. 外部依赖
- **当前（M2）**：PostgreSQL（档案+审计，可选）、Neo4j（知识图谱，可选）、Chroma（向量库，可选，本地文件）、sentence-transformers（本地 embedding，可选）。**全部可选——关闭后核心计算不受影响。**
- **目标（M3+）**：自部署模型服务(vLLM)、OAuth 提供方、Shopify/Amazon API。每项落地时本文件更新 + 审查矩阵安全/性能/SRE 全项对其生效。

## 5. 跨切面工业级约束（审查恒查）
- **PII 安全**：SSN/收入等传输+存储加密、最小权限、审计可追溯;日志/错误信息**不得泄露 PII**。
- **数据驻留**：不出境、不接第三方 LLM API。
- **Guardrail**：涉及金额必出自规则引擎,模型不得编造数字;结论可回链法条。
- **幂等**：M2+ 的写入/摄取/外部调用须幂等(重试/重复提交不重复计、不损坏)。
- **可观测性**：M2+ 关键分支补 metrics + Error 日志,出事 1 分钟内可定位。

## 6. 审查含义（与 `docs/code_review_matrix.md` 配套）
- 按 §2 当前真实组件裁剪适用风险;§3 目标架构落地后再解锁对应安全/性能/SRE 全项。
- **当前每个 PR 必做**：数值精确到分(自建独立参考逐分核,不只对引擎自身)+ 输入健壮性 + 纯无状态可扩展 + PII/日志不泄露;矩阵其余项按存在性裁剪。
