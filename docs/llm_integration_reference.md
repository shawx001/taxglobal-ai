# LLM 集成参考：awesome-llm-apps 可用模式清单

> 来源：https://github.com/Shubhamsaboo/awesome-llm-apps
> 调研日期：2026-06-08
> 决策：Shaw 同意使用外部 LLM API + PII 脱敏（同日）
> 维护：每个 milestone 实现时更新"状态"列

## 架构决策

| 决策 | 内容 |
|---|---|
| **LLM 用途** | 仅做"耳朵"（意图分类）和"嘴"（自然语言响应），不做"大脑"（税务计算） |
| **计算引擎** | 100% 本地规则引擎，LLM 不碰任何数字 |
| **PII 处理** | 发送前经 `sanitizer.py` 脱敏：SSN → `***-**-XXXX`，姓名/邮箱 → `[redacted]`，金额保留 |
| **推荐 Provider** | GPT-4o-mini（意图分类 + 响应生成），备选 Claude 3.5 Haiku / DeepSeek |
| **降级策略** | `ENABLE_LLM=false` 时降级到现有关键词分类 + 模板响应，所有测试不变 |

## LLM 在架构中的位置

```
用户查询
  ↓
[PII Sanitizer] ← backend/audit/sanitizer.py（M2.9，同时用于审计和 LLM 调用）
  ↓
① [LLM] 意图分类 + 参数提取 ← 替代 backend/orchestrator/intent.py 的 keyword classify
  ↓
  ├─ skill_route → 引擎计算 → guardrail     ← 100% 本地，不变
  ├─ kb_route → GraphRAG 检索               ← 100% 本地，不变
  └─ clarify
  ↓
② [LLM] 自然语言响应生成 ← 替代 backend/orchestrator/nodes.py 的 template format_node
  ↓
[Guardrail] 验证 LLM 没有篡改引擎数字
  ↓
返回用户
```

---

## 可用模式清单（16 项）

### M2.9 — 审计日志（当前）

| # | 模式 | 来源项目 | 描述 | 状态 |
|---|---|---|---|---|
| 1 | **SHA-256 hash-chain 审计链** | `trust_gated_agent_team` | 每条审计记录存 entry_hash + prev_hash，篡改任何历史记录会断链。参考其 `sequence + timestamp + agent + action + input_hash + output_hash + prev_hash` 结构。 | ✅ 已加入 M2.9 Codex prompt |

### M3.1 — LLM 意图分类

| # | 模式 | 来源项目 | 描述 | 状态 |
|---|---|---|---|---|
| 2 | **LLM 分类 → 专业数据库路由** | `rag_database_routing` | 架构与我们的 `classify_node → skill_route/kb_route` 几乎一致，只是用 LLM 做分类而不是关键词。直接参考其 router prompt 结构。 | 🔲 M3.1 |
| 3 | **意图分类 → 专家 agent 分发** | `multi_mcp_agent_router` | `User Query → Router → Classifies intent → Specialist agent`。其 `AGENTS` 字典注册方式可参考改进我们的 `INTENT_SKILL_MAP`。 | 🔲 M3.1 |

### M3.2 — LLM 响应生成

| # | 模式 | 来源项目 | 描述 | 状态 |
|---|---|---|---|---|
| 4 | **5 步事实验证 + 来源分级** | `awesome_agent_skills/fact-checker` | LLM 生成税务回答后走 fact-check pass：核对引擎数字是否被 LLM 改动、来源是否可追溯。其 source hierarchy（官方数据 > 权威出版物 > 一般来源）与我们的 `source_ids` 体系直接对接。 | 🔲 M3.2 |

### M3.3 — KB 检索增强

| # | 模式 | 来源项目 | 描述 | 状态 |
|---|---|---|---|---|
| 5 | **CRAG 检索质量评分 + 查询改写** | `rag_tutorials/corrective_rag` | LLM 评估检索结果质量，差的自动改写查询重试。在 `kb_route_node → hybrid_search` 之间加一层评分。使用 LangGraph workflow。 | 🔲 M3.3 |
| 6 | **Neo4j 多跳推理 + 可验证引用链** | `rag_tutorials/knowledge_graph_rag_citations` | 我们已有 Neo4j！目前只用图做实体检索。此项目展示多跳遍历（A 法规引用 B 条款，B 修改了 C 税率）+ 每个答案自动附带引用路径。直接升级 `backend/knowledge/search.py`。 | 🔲 M3.3 |
| 7 | **Cross-encoder reranking** | `rag_tutorials/hybrid_search_rag` | 检索后用 cross-encoder 重排序。我们的 hybrid_search 目前是 vector score + graph score 简单加权。可用 FlashRank（本地，零 API 费用）代替 Cohere。 | 🔲 M3.3 |

### M3 — Token 优化 & 文档处理

| # | 模式 | 来源项目 | 描述 | 状态 |
|---|---|---|---|---|
| 8 | **SmartCrusher + CacheAligner token 压缩** | `llm_optimization_tools/headroom_context_optimization` | 发给外部 LLM 的 context 压缩 76-92%。SmartCrusher 只保留"首项 + 末项 + 异常值 + 查询相关项"。CacheAligner 稳定 prompt prefix 提高 API 缓存命中率。 | 🔲 M3 |
| 9 | **Vision model 文档识别（无 OCR）** | `rag_tutorials/vision_rag` | "No OCR Required" — 直接用 vision model 理解 W-2/1099 图片中的表格和数字。用于 M3 `extract_w2` skill。省掉 Tesseract + 模板匹配 pipeline。 | 🔲 M3 |
| 10 | **多角色文档分析团队** | `agent_teams/ai_legal_agent_team` | 3 角色（Researcher / Analyst / Strategist）+ Team Lead 协调。PDF → embedding → 多 agent 并行分析 → 汇总。用于税务文档处理：一个 agent 提取数字，一个验证合规，一个生成建议。 | 🔲 M3 |
| 11 | **MCP 连接器模式** | `mcp_ai_agents/multi_mcp_agent_router` | 通过 MCP 协议连接外部工具（银行 API、政府税务接口、Shopify）。作为 M3 连接器层的备选架构方案（vs 直接 OAuth + REST）。 | 🔲 M3 |

### M4 — 训练闭环

| # | 模式 | 来源项目 | 描述 | 状态 |
|---|---|---|---|---|
| 12 | **TextGrad + MIPRO prompt 自动优化** | `ai_self_evolving_agent` (EvoAgentX) | 在验证集上测试 → 自动调整 prompt + workflow 结构。HotPotQA 上 63.58% → 71.02%。用于意图分类 prompt 迭代优化。 | 🔲 M4 |
| 13 | **12 种 RAG 故障模式分类器** | `rag_tutorials/rag_failure_diagnostics_clinic` | KB 检索失败自动分类：检索幻觉 / chunk 切分错误 / embedding 不匹配 / 索引过期 / 查询路由错误等 12 种。建 incident library 追踪系统性问题。 | 🔲 M4 |

### M5 — 前端 & 用户体验

| # | 模式 | 来源项目 | 描述 | 状态 |
|---|---|---|---|---|
| 14 | **A2UI 生成式 UI** | `generative_ui_agents/generative-ui-starter-project` | Agent 返回 JSON 描述 UI → 前端自动渲染组件（表单、计算卡片、进度图表）。Next.js + CopilotKit + LangGraph。需要前端重构。 | 🔲 M5 |
| 15 | **Agentic Canvas 仪表盘** | `generative_ui_agents/ai-dashboard-canvas-agent` | Agent 往 canvas 上放图表/KPI/面板。用于税务总结仪表盘（effective rate、州税对比、deadline 时间线）。Next.js + CopilotKit + Google ADK。 | 🔲 M5 |
| 16 | **引导式报税 UI 交互** | `generative_ui_agents/ai-financial-coach-agent` | Budget → Savings → Debt 三步引导流程，streaming status + report tab。与我们的"档案 → 计算 → 建议"同构。CopilotKit + AG-UI 协议。 | 🔲 M5 |

---

## 评估后排除的项目

| 类别 | 项目 | 排除原因 |
|---|---|---|
| **Finance Agent Team** | `agent_teams/ai_finance_agent_team` | 代码实际只做 YFinance 股票查价，零财务计算。名字误导。 |
| **Data Analyst skill** | `awesome_agent_skills/data-analyst` | SQL/Pandas 数据分析。我们的税务计算是确定性规则引擎，不走 SQL 路线。 |
| **Python Expert skill** | `awesome_agent_skills/python-expert` | 让 LLM 生成 Python 计算脚本。直接违反 AGENTS.md 核心约束（规则引擎是唯一真相源，LLM 输出不可信）。 |
| **Chat with PDF** | `chat_with_X_tutorials/chat_with_pdf` | 通用 PDF 问答，无税务文档结构化提取能力。 |
| **Investment Agent** | `single_agent_apps/ai_investment_agent` | 股票投资分析，非税务。 |
| **游戏/音乐/旅行等** | 多个 | 领域完全无关。 |
| **Local RAG (Llama/Ollama)** | 多个 | 已决定用外部 API，不自部署模型。 |
| **LLM Fine-tuning** | `llm_finetuning_tutorials/*` | 不训练基座模型。 |
| **大部分 starter agents** | 多个 | Demo 级代码，架构不可复用。 |

---

## 落地优先级

```
★ 投入产出比最高的 3 个：
  #1 hash-chain 审计 — 30 行代码，审计防篡改能力跳一个量级（已加入 M2.9）
  #6 Neo4j 多跳引用 — 已有 Neo4j + 知识图谱，只需加遍历逻辑
  #8 headroom 压缩 — 接入外部 LLM 后直接省 70-90% token 费用

时间线：
  M2.9: #1 hash-chain ← 现在
  M3.1: #2 + #3 LLM 路由/分类
  M3.2: #4 fact-checker guardrail
  M3.3: #5 + #6 + #7 KB 增强三件套
  M3:   #8 + #9 + #10 + #11 token 优化 + 文档 + 连接器
  M4:   #12 + #13 训练闭环
  M5:   #14 + #15 + #16 前端重构
```
