# 路线图与 18 Skills 现状映射

> 目的:让"我们现在在哪、18 Skills 做到哪"始终可见,不再"看不到"。
> 依据:`TaxGlobal_AI_项目计划书_v3.1.md`(M0–M5 里程碑 + 18 Skills 架构)。
> 维护:每完成一步由 Claude 更新本表 + `feature_status.md`。最后更新:2026-06-13（M3 对话式 AI + W-2 识别 + Phase C 检索增强 全部合并）。

## 一、里程碑路线图(M0–M5)与当前位置

| 里程碑 | 周期 | 交付 | 状态 |
|---|---|---|---|
| **M0 原型** | — | 高保真可交互原型,全流程可点可算 | ✅ 已完成 |
| **M1 引擎硬化** | 第 1–3 周 | tax-engine 后端服务 + 黄金测试集 + CI;前后端结果一致 | ✅ **已完成并正式关闭（2026-06-07）** |
| **M2 Agent + 知识层** | 第 3–5 周 | **18 Skills**(LangChain 编排)+ GraphRAG(MVP) | ✅ **已完成并正式关闭（2026-06-09）** |
| **M3 对话式 AI + 多模态 + 检索增强** | 第 5–7 周 | LLM 对话(意图/响应/fact-check)、Copilot 聊天 UI、W-2 识别、Phase C 检索增强 | 🟡 **核心已交付（2026-06-13）**；连接器/自训模型推迟（见下） |
| **M4 训练闭环 + 连接器** | 第 7–8 周 | Trace 回流 + LoRA + Eval Harness + OAuth/Shopify/Amazon 连接器 | 🟡 **管道全交付（2026-06-14）**；真实训练/真实 OAuth 待外部(算力/凭据) |
| **M5 合规与上线** | 第 9–10 周 | 安全/合规/可观测 + 限流上线 + Demo 联调 | 🔲 未开始 |

**M1 关闭总结（2026-06-07）**:REQ-009 引擎三块已齐(Block 1/2/3 已合并);REQ-002 前端总览已接到单次 `income_tax_summary`;Step A 2026 税年数据;Step B 扩州(WA excise/NJ/PA/OR);Step C1–C4 全部 50 州+DC 覆盖(51 jurisdictions);PR #40 deepcopy→freeze 性能优化;PR #41 前端 50 州+DC 动态下拉。unittest + ruff 全绿。M1 正式关闭。下一阶段进入 M2 Skills/Agent + 知识层。

**M2 关闭总结（2026-06-09）**:M2.1 三库基础设施(PG+Neo4j+Chroma+embedding);M2.2 知识图谱建模+入库;M2.3 GraphRAG 混合检索 API;M2.4 档案持久化 API;M2.5 LangChain Skill 框架(5 引擎 Skills);M2.6 Guardrail 中间件(金额验证+schema+4级升级+PII);M2.7 LangGraph Workflow 编排器(意图→Skill/KB→Guardrail→响应);M2.8 KB 驱动税务提醒+截止日;M2.9 审计日志(ASGI middleware+SHA-256 哈希链+PII 脱敏);M2.10 集成验收测试(7项验收标准全绿)。共 PR #45–#63,新增 233 M2 测试+13 集成验收测试,全套 369 tests + ruff 全绿。ARCHITECTURE.md §2 更新为 M2 完整架构。下一阶段进入 M3 连接器+多模态。

**M3 交付总结（2026-06-13）**:M3.1 LLM Provider 抽象层(OpenAI 兼容+PII 脱敏装饰器+failover);M3.2 LLM 意图分类(7 意图,失败回退关键词,50 条测试集 100%);M3.3 LLM 自然语言响应(answer_text 附加,结构化 answer 原样保留);M3.4 Fact-checker(金额逐分核查,篡改/幻觉 fail-closed,含中文/k/USD 格式+反馈重试);M3.5 前端 Copilot 聊天 UI + SSE 流式 + 多轮记忆(查询改写)+ LLM 参数抽取 + tax-rate 概览;M3.6 W-2 拍照/PDF 识别(Vision,GPT-4o 真实文件 9/9 到分准,PII 三重防泄漏);M3.7 Token 优化 + 用量成本统计 + admin 端点;M3.8 LLM 端点限流。Phase C 检索增强:C.1 cross-encoder 重排、C.2 CRAG 纠错、C.3 Neo4j 多跳。共 PR #66–#81,640+ tests + ruff + CI 全绿,每 PR CI 绿才合并。
**范围分歧(诚实记录)**:计划书原 M3="OAuth/Shopify/Amazon 连接器 + 自训 Copilot 模型";实际交付="对话式 AI(外部 DeepSeek/OpenAI LLM)+ W-2 识别 + 检索增强"。**电商连接器 + 自训模型未做**,归入 M4(自训模型本就属训练闭环)。**外部依赖待开**:vision key(OpenAI 已验证,境内合规可切 SiliconFlow)、重排模型缓存(已下)、Neo4j 多跳(待起服务)。

**M4 交付总结（2026-06-14）**:M4.1 **Eval Harness**(意图准确率 + fact-check 保真度两维 + 加权总分 + ≥0.80 部署门禁;离线确定性、可接任意 classifier,PR #90);M4.2 **Trace→SFT 数据管道**(审计日志/JSONL 双源 → 质量筛选[用户纠正=gold、predicted 仅 fact-check pass+高置信、丢 block]→ chat 格式 SFT,新旧 20%/80% 混合,PR #91);M4.3 **LoRA 训练管道**(Qwen2.5-0.5B,TRL+PEFT,训练后过 M4.1 门禁才放行;训练依赖可选[requirements-training.txt]+惰性 import,不进 CI/serving,PR #92);M4.4 **连接器框架**(Shopify[自申报]/Amazon[平台代缴]sandbox 适配器 + OAuth 跳转脚手架 + 桥接 nexus_estimate + 路由,PR #93)。共 PR #90–#93,712 tests(1 smoke skip)+ ruff + CI 全绿,每 PR CI 绿+Copilot 处理后合并。
**外部依赖待激活(诚实划线)**:① LoRA **真实训练**需算力 + HF 模型下载 + 安装训练 extras;② 连接器**真实连接**需 Shaw 注册的 OAuth 应用与凭据。二者均已建到"给凭据/算力即可跑"的可插拔边界;sandbox/纯逻辑全程可跑、CI 覆盖。规则引擎仍是唯一数字真相,LoRA 只调意图分类+措辞。

## 二、18 Skills 清单与现状

**关键澄清**:这里的"Skills"是**计划书里 LangChain Agent Runtime 编排的应用层技能**(M2),**不是** Claude Code 的 `/skill`。每个 Skill 涉及金额的输出必须来自**规则引擎**,自有模型不得编造数字(计划书 Guardrail)。

计划书 v3.1 §九点名了 11 个(原文以"等"结尾,共 18 个;未点名的 7 个待 M2 启动时补全,**此处不臆造**)。计算内核(引擎函数)现状:

| # | Skill | 依赖的引擎函数/能力 | 引擎内核状态 |
|---|---|---|---|
| 1 | `calculate_income_tax` | `income_tax_summary`(W-2/自雇/资本利得/NIIT/FEIE 三块 + WA/NJ/PA/OR 州扩展) | ✅ 已完成 |
| 2 | `assess_feie` | `feie_estimate` | ✅ 已完成 |
| 3 | `analyze_rsu` | `rsu_tax_estimate` | ✅ 已完成 |
| 4 | `track_crypto` | `crypto_gain_estimate` + `_crypto_state_tax` | ✅ 已完成 |
| 5 | `detect_nexus` | `nexus_estimate`(经济联结 Wayfair) | ✅ 已完成 |
| 6 | `parse_profile` | 档案解析/编排(= REQ-002 前端总览入口) | ✅ 可用(REQ-002 前端总览) |
| 7 | `classify_transaction` | 交易分类(加密/电商品类),待 KB/规则 | 🔲 待 M2 |
| 8 | `rank_nomad_cities` | 数字游民城市排名,待数据/规则 | 🔲 待 M2 |
| 9 | `extract_w2` | Vision W-2/PDF 识别(多模态) | ✅ 已完成(M3.6;GPT-4o,真实文件验证到分准;`expose_via_api=False` 只走 `/api/documents`) |
| 10 | `generate_form` | 表单生成(1040 等) | 🔲 待 M4+ |
| 11 | `check_treaty` | 税收协定/FTC(关联 REQ-004 海外被动收入) | 🔲 待 M2+ |
| 12–18 | (计划书未点名,TBD) | 待 M2 启动时枚举 | 🔲 待定义 |

**小结**:18 个中已点名 11 个;其中 **5 个 Skill 的权威计算内核已在引擎里就绪**(calculate_income_tax / assess_feie / analyze_rsu / track_crypto / detect_nexus)——M2 主要是把这些引擎函数封成 LangChain Skill(薄封装 + guardrail)并接 GraphRAG,而非重写计算。

## 三、为什么 Skills 还没动(诚实说明)
1. **顺序使然**:Skills 是 Agent 编排层(M2),需调用底层规则引擎(M1)+ 知识库(GraphRAG)。引擎未夯完、KB 未建,Agent 层无从编排。计划本就把它排在引擎之后。
2. **可见性缺口(已修)**:此前埋头引擎分块,未维护 Skills/里程碑视图;本文件 + 记忆补上,之后每步更新。

## 四、决定(2026-06-03)
Shaw 选择**先收尾引擎 + 前端**:REQ-002 前端总览已完成 M1 收尾，之后进入 M2 的 Skills/Agent 层。
