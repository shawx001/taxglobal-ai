# M3 Step Plan — AI 对话 + 文档识别

> 目标：让用户第一次真正"感知到 AI"——打字问税务问题、AI 用人话回答；拍 W-2 照片自动填表。
> 周期：第 5–7 周（约 10 个工作日）。
> 原则：workflow > agent 默认；规则引擎 = 唯一真相；LLM 只做"耳朵"（理解）和"嘴"（表达），不做"大脑"（计算）；小步可测；一步一 PR。
> 依据：`ARCHITECTURE.md` §3 + `docs/agent_architecture_principles.md` + `docs/llm_integration_reference.md`。
> 维护：每步完成后打勾 + 更新 `feature_status.md` + `roadmap_skills_status.md`。

---

## 大白话：M3 做完能干嘛 + 验收标准

### M3 做完用户能做什么（对比 M2）

| 功能 | M2（现在） | M3 做完后 |
|---|---|---|
| 算税 | 手动填数字 → 出结果 | **不变**，原来的计算器照常 |
| 问问题 | 关键词匹配 → JSON 结果 | **打字问"加州年薪 20 万怎么省税"→ AI 用人话回答 + 引擎精确数字 + 法条来源** |
| 搜知识 | 关键词 → 结构化结果 | **自然语言搜 → AI 组织成段落回答 + 来源引用** |
| 填 W-2 | 手动一个个输入 | **拍 W-2 照片 → 自动识别 Box 1/2/17 等字段 → 一键填入计算表** |
| 安全 | Guardrail 阻止伪造金额 | **新增 Fact-checker：LLM 回答的数字必须和引擎一致，篡改即拦截** |
| 省钱 | — | **Token 压缩 70-90%，API 费用可控** |

### 诚实说明

M3 的 LLM 只负责**理解用户意图 + 组织自然语言回答**。所有税务金额 100% 来自规则引擎。LLM 回答里的每个数字都经过 fact-checker 比对引擎输出——LLM 改了一分钱就会被拦截。

### 验收标准（M3 怎么算通过）

1. 前端有 Copilot 聊天窗口，用户打字问问题 → AI 用自然语言回答
2. "加州年薪 15 万交多少税" → 返回人话回答 + 联邦税 $24,734.00 + CA 州税（到分准确）+ IRS 来源
3. LLM 意图分类准确率 ≥ 95%（在测试集上）
4. Fact-checker 拦截 100% 的金额篡改（引擎说 $24,734 LLM 说 $24,700 → 拦截）
5. 拍 W-2 照片 → 正确提取 Box 1 wages、Box 2 federal withheld 等字段
6. `ENABLE_LLM=false` → 降级到 M2 关键词模式，所有现有测试不变
7. PII 在发送给 LLM API 前已完全脱敏（SSN/姓名/邮箱不出境）

---

## 技术栈决策（2026-06-09 Shaw 拍板）

| 层 | 技术 | 说明 |
|---|---|---|
| **LLM Provider** | **DeepSeek V4 Flash**（意图分类+响应）/ **V4 Pro**（复杂推理备选）| Shaw 选择；抽象层支持 failover 到 GPT-4o-mini / Claude Haiku |
| **Provider 接口** | **OpenAI SDK + base_url 覆写** | DeepSeek API 100% 兼容 OpenAI 协议，`openai` Python SDK + `base_url="https://api.deepseek.com"` |
| **定价** | V4 Flash: $0.14/MTok input, $0.28/MTok output; cached input $0.0028/MTok | V4 Pro: $0.435/$0.87 MTok（75% 折扣后）|
| **Failover** | DeepSeek 可用性 ~97.8%，必须有备选 Provider | Provider 抽象层自动 failover → GPT-4o-mini |
| **PII 管道** | **复用 `backend/audit/sanitizer.py`** | 发送前脱敏，接收后上下文还原 |
| **Vision** | **DeepSeek V4 Vision**（W-2 OCR）/ GPT-4o 备选 | DeepSeek V4 Vision 支持文档提取，~90 KV cache/图，效率高；GPT-4o 作为 fallback |
| **前端聊天** | **现有 HTML + 浮动聊天窗口** | 不重构 Next.js；在 index.html 加右下角气泡 |
| **流式输出** | **SSE（Server-Sent Events）** | 比 WebSocket 简单；FastAPI StreamingResponse |
| **Feature Flag** | **`ENABLE_LLM`** | 关闭 = 降级到 M2 关键词+模板模式 |

### LLM 在架构中的位置

```
用户输入（前端聊天框）
  ↓
[PII Sanitizer] ← backend/audit/sanitizer.py（M2 已有）
  ↓
① [LLM] 意图分类 + 参数提取 ← 替代 keyword classify
  ↓
  ├─ skill_route → 引擎计算 → guardrail     ← 100% 本地，不变
  ├─ kb_route → GraphRAG 检索               ← 100% 本地，不变
  └─ clarify（需要更多信息）
  ↓
② [LLM] 自然语言响应生成 ← 替代 template format_node
  ↓
[Fact-checker] 比对 LLM 回答 vs 引擎原始数字
  ↓
[SSE Stream] → 前端聊天窗口
```

---

## 步骤拆分

### Phase A：让 AI 开口说话（M3.1 – M3.5）

---

### M3.1 LLM Provider 抽象层

**目标**：接入外部 LLM API，统一接口，PII 安全管道。

**交付**：
- `backend/llm/__init__.py` — 包初始化
- `backend/llm/provider.py` — 统一 LLM 调用接口
  - `LLMProvider` 抽象基类：`classify(query) → Intent`、`generate(prompt, context) → str`、`stream(prompt, context) → AsyncIterator[str]`
  - `DeepSeekProvider` — 默认实现（OpenAI SDK + base_url）
  - `OpenAIProvider` / `ClaudeProvider` — 备选
  - `MockProvider` — 测试用，返回确定性结果
- `backend/llm/sanitize_pipeline.py` — LLM 专用 PII 管道
  - 发送前：调用 `sanitize_payload()` 脱敏
  - 接收后：上下文还原（引擎数字原样注入）
- `backend/config.py` 新增：
  - `ENABLE_LLM: bool`（默认 False，M2 行为不变）
  - `TAXGLOBAL_LLM_PROVIDER: str`（"deepseek" / "openai" / "claude"）
  - `TAXGLOBAL_LLM_API_KEY: str`
  - `TAXGLOBAL_LLM_MODEL: str`（默认 "deepseek-v4-flash"；可选 "deepseek-v4-pro"）
  - `TAXGLOBAL_LLM_FALLBACK_PROVIDER: str`（备选 Provider，默认 "openai"）
  - `TAXGLOBAL_LLM_FALLBACK_API_KEY: str`
  - `TAXGLOBAL_LLM_FALLBACK_MODEL: str`（默认 "gpt-4o-mini"）

**测试**：
- `test_m3_1_llm_provider.py`
  - MockProvider 返回确定性结果
  - PII 管道：SSN 脱敏后再发送、金额保留
  - `ENABLE_LLM=false` → 不调用任何外部 API
  - Provider 工厂：根据配置返回正确 Provider

**验收门**：
```powershell
python -m unittest discover -s tests
python -m ruff check engine backend tests
```

**状态**：✅ 已合并（PR #66，2026-06-09）。实现说明：接口为 `complete()/stream()` 而非 `classify()/generate()`；`SanitizedProvider` 装饰器透明脱敏。

---

### M3.2 LLM 意图分类

**目标**：用 LLM 替换关键词匹配，准确理解复杂自然语言查询。

**交付**：
- `backend/orchestrator/intent.py` 修改
  - 新增 `llm_classify(query, provider) → IntentResult`
  - System prompt：严格 JSON 输出，7 种意图（income_tax / feie / rsu / crypto / nexus / knowledge / clarify）
  - 参数提取："加州年薪 20 万有 RSU" → `{state: CA, w2_wages: 200000, has_rsu: true}`
  - 降级：LLM 超时/报错 → 回退到 `keyword_classify()`
- `backend/orchestrator/graph.py` 修改
  - `classify_node` 根据 `ENABLE_LLM` 选择 LLM 或关键词分类
- `data/llm_prompts/intent_classify.txt` — System prompt（版本化，可迭代）

**测试**：
- `test_m3_2_llm_intent.py`
  - 用 MockProvider 测 10+ 种查询意图分类
  - 复杂查询："我在加州年薪 20 万，有 50 股 RSU 归属，长期持有的加密卖了 5 万利润，怎么算税" → 正确拆解
  - 降级测试：Provider 抛异常 → 回退关键词匹配
  - 准确率测试：50 条测试集 ≥ 95%

**状态**：✅ 已合并（PR #67，2026-06-10）。实现说明：函数名 `llm_classify_intent()`；system prompt 硬编码在 `intent.py`（非 `data/llm_prompts/` 文件）；参数提取仍用 M2 正则（LLM 参数提取推迟）；置信度阈值 0.6；全防御性解析（非 dict JSON/NaN/异常均回退关键词）；LLM 输出一律不进日志（PII）。准确率测试集（≥95%）推迟到接入真实 API 后。

---

### M3.3 LLM 自然语言响应生成

**目标**：引擎结果 + 来源 → LLM 组织成自然语言回答。

**交付**：
- `backend/orchestrator/response.py` — 新模块
  - `llm_format_response(query, answer, sources) → str | None`（任何失败返回 None，调用方保留 M2 模板）
  - System prompt 硬编码在模块内，严格约束：
    - 金额必须与引擎输出精确到分一致（可加 $ 和千分位格式，不得四舍五入、不得编造）
    - 必须包含来源引用
    - 口吻友好、用中文（或跟随用户语言）
    - 不给投资/理财建议
- `backend/orchestrator/nodes.py` 修改
  - `format_node` → `ENABLE_LLM=true` 时新增 `answer_text` 字段，结构化 `answer` 原样保留

**测试**：
- `test_m3_3_response.py`
  - MockProvider 返回模板化自然语言
  - 金额保持精确：引擎输出 $24,734.00 → 响应中出现 $24,734.00
  - 来源引用保留
  - 降级：LLM 挂 → 返回 M2 模板格式

**状态**：✅ 已合并（PR #69，2026-06-10）。实现说明：新模块 `backend/orchestrator/response.py`（`llm_format_response()`）；LLM 文本作为**新增** `answer_text` 字段，结构化 `answer` 原样保留（M3.4 fact-checker 的比对基准）；错误/澄清路径不调 LLM；system prompt 硬编码；sanitizer 9 位金额误掩码缺陷已在该 PR 一并修复。

---

### M3.4 Fact-checker Guardrail

**目标**：验证 LLM 响应没有篡改引擎数字。

**交付**：
- `backend/guardrail/fact_checker.py` — 新增
  - `check_response_fidelity(llm_response: str, engine_result: dict) → FactCheckResult`
  - 5 步验证：
    1. **数字匹配**：提取 LLM 响应中所有 $ 金额，比对引擎输出
    2. **来源追溯**：引用的来源 ID 必须在引擎 citations 中存在
    3. **无幻觉金额**：LLM 响应中出现的金额，引擎输出中不存在 → 告警
    4. **无虚假建议**：不得包含"建议投资/买保险/开公司"等越界内容
    5. **合规检查**：不得包含"保证/确定/一定"等绝对性表述
  - 结果：PASS / WARN（轻微偏差，附注释）/ BLOCK（金额篡改，返回引擎原始结果）
- `backend/guardrail/validator.py` 修改 — 集成 fact-checker

**测试**：
- `test_m3_4_fact_checker.py`
  - 正常响应 → PASS
  - 金额被修改 $24,734 → $24,700 → BLOCK
  - 凭空出现引擎没有的金额 → WARN
  - 包含"保证"→ WARN
  - 来源 ID 不存在 → WARN

**状态**：🚧 PR 进行中（codex/m3-4-fact-checker）。实现说明：新增 `backend/guardrail/fact_checker.py`，用 Decimal 归一化比对 LLM `answer_text` 中所有 `$` 金额与结构化引擎输出；金额不匹配则 fail-closed 丢弃 LLM 文本，WARN 仅附注不拦截。

---

### M3.5 前端 Copilot 聊天 UI

**目标**：前端加浮动聊天窗口，连接 M3.1–M3.4 的后端。

**交付**：
- `backend/routes/assistant_routes.py` 修改
  - 新增 `POST /api/assistant/stream` — SSE 流式端点
  - 复用 `run_assistant_query()` + LLM stream
- `frontend/copilot.js` — 新增
  - 右下角浮动聊天气泡 → 点击展开聊天窗口
  - 消息输入 → POST /api/assistant/stream → SSE 逐字显示
  - 消息历史（localStorage）
  - 引用卡片：展示来源 ID，可点击
  - Markdown 渲染（代码块、列表、加粗）
  - 打字中动画 / 加载状态
- `frontend/copilot.css` — 新增
  - 聊天窗口样式（与现有设计风格一致）
- `frontend/index.html` 修改
  - 引入 copilot.js + copilot.css

**测试**：
- `test_m3_5_stream_endpoint.py`
  - SSE 端点返回正确的 text/event-stream content-type
  - 流式输出包含 intent + answer + sources
  - `ENABLE_LLM=false` → 降级到同步 JSON 响应

**状态**：✅ 本地完成（branch m3/local-completion，多agent评审通过）。实现说明：`POST /api/assistant/stream` 始终 SSE（flag 关闭时无 text 事件，`/query` 保持纯 JSON）；**fact-check 完成后才开始流式**（不转发原始 LLM token），通过的 `answer_text` 重新切块给前端打字效果；前端复用原型已有聊天壳（`frontend/copilot.js` 为新传输层，全部动态文本 HTML 转义），假大脑 KB 仅作"离线演示"兜底；tax_year 未显式传时从问题文本解析（"2025年…"→2025 规则）；审计中间件新增 SSE 响应重建（meta+answer 入审计，action=assistant:stream）。测试文件实际为 `test_m3_5_stream.py`，13 个测试。

---

### Phase B：文档智能（M3.6 – M3.7）

---

### M3.6 W-2 / 1099 拍照识别（extract_w2 Skill）

**目标**：用户拍 W-2 照片 → 自动提取字段 → 填入计算表。

**交付**：
- `backend/skills/extract_w2.py` — 新 Skill
  - 接收图片（base64 或 multipart upload）
  - 调用 Vision API（DeepSeek-VL / GPT-4o）识别 W-2 表单
  - 提取字段：
    - Box 1: Wages, tips, other compensation
    - Box 2: Federal income tax withheld
    - Box 3: Social security wages
    - Box 4: Social security tax withheld
    - Box 5: Medicare wages
    - Box 6: Medicare tax withheld
    - Box 15: State
    - Box 16: State wages
    - Box 17: State income tax
  - 返回结构化 JSON + 置信度分数
  - **PII 安全**：图片发送给 Vision API 前，日志不记录原图；提取完成后不存储图片
- `backend/routes/document_routes.py` — 新增
  - `POST /api/documents/extract-w2` — 上传 W-2 图片 → 返回提取字段
- `backend/skills/registry.py` 修改 — 注册 extract_w2
- `frontend/w2-upload.js` — 新增
  - W-2 报税页面加"拍照/上传"按钮
  - 调用 extract API → 自动填入表单字段
  - 用户可手动修正 → 确认后提交计算

**测试**：
- `test_m3_6_extract_w2.py`
  - MockProvider 返回模拟 W-2 提取结果
  - 提取字段格式正确（金额为 Decimal/str，非 float）
  - 缺失字段标记为 null + 置信度 0
  - PII 测试：上传请求日志不含图片原始数据

**状态**：🔲 未开始

---

### M3.7 Token 优化 + 成本监控

**目标**：压缩发送给 LLM 的 context，减少 70-90% token 费用。

**交付**：
- `backend/llm/token_optimizer.py` — 新增
  - SmartCrusher：长 context 压缩（只保留关键信息）
  - CacheAligner：稳定 prompt prefix 提高 API cache 命中率
  - Token 计数器：tiktoken 估算每次调用 token 数
- `backend/llm/usage_tracker.py` — 新增
  - 记录每次 LLM 调用的 token 数 + 费用估算
  - 日/周/月聚合
- `backend/routes/admin_routes.py` 修改
  - 新增 `GET /api/admin/llm-usage` — LLM 使用量统计（需 admin token）

**测试**：
- `test_m3_7_token_optimizer.py`
  - SmartCrusher 压缩比 ≥ 50%
  - CacheAligner prefix 稳定性测试
  - Token 计数器准确性

**状态**：🔲 未开始

---

## 步骤总览

| 步骤 | 标题 | 依赖 | 预估工作量 | 状态 |
|---|---|---|---|---|
| **M3.1** | LLM Provider 抽象层 | 无 | 1 天 | ✅ PR #66 |
| **M3.2** | LLM 意图分类 | M3.1 | 1 天 | ✅ PR #67 |
| **M3.3** | LLM 自然语言响应 | M3.1 | 1 天 | ✅ PR #69 |
| **M3.4** | Fact-checker Guardrail | M3.3 | 1 天 | 🚧 |
| **M3.5** | 前端 Copilot 聊天 UI | M3.2 + M3.3 + M3.4 | 2 天 | 🔲 |
| **M3.6** | W-2 拍照识别 | M3.1 | 2 天 | 🔲 |
| **M3.7** | Token 优化 + 成本监控 | M3.1 | 1 天 | 🔲 |

**总计：~9 个工作日**

---

## 关闭标准

全部 7 项验收标准通过 + 所有测试绿 + ruff 绿 + ARCHITECTURE.md 更新 + feature_status.md 更新 = M3 正式关闭。

Phase C（KB 增强：CRAG / Neo4j 多跳 / Cross-encoder）和 Phase D（OAuth / 连接器）推迟到 M3.5 或 M4。
