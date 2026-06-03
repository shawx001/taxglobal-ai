# M2 Agent / 知识库 架构北极星（生产级 LLM 系统原则）

> 用途：M2（LangChain Agent Runtime + 18 Skills + GraphRAG 知识库）**动工前**先定对架构,避免把最复杂、最易出事的一层堆成屎山或上线崩。
> 来源：Anthropic《Building Effective Agents》、HumanLayer《12-Factor Agents》、vibe-coding-cn。**与本项目既有 guardrail(金额必出自规则引擎)完美一致。**
> 现状：M1(引擎)无 LLM,本文件是 M2 设计约束,不是当前 PR 要求。

## 0. 一句话
**成功的"agent"大多是工程扎实的传统软件 + 少量 LLM 点缀**;LLM 是决策/表达者,**不是计算或真相的替代**。

## 1. 默认用 Workflow,不轻易上 Agent（Anthropic：从简）
- 能预先画出决策树的任务 → 用 **workflow**(代码掌控流程),更准、更可控、更便宜;只有真需要模型自主决策才用 agent(模型掌控流程)。
- 我们的 18 Skills 多是**确定性工具调用**(算税/查 KB/判 Nexus) → **绝大多数是 workflow**。
- 5 种 workflow 模式备选:prompt chaining / routing / parallelization / orchestrator-workers / evaluator-optimizer。
- **先简单,量化一切,有可测收益再加复杂度**(复杂度换的是延迟和成本)。

## 2. Guardrail:规则引擎是唯一真相,LLM 输出当不可信（12-Factor F2/F4 + 本项目铁律）
- 涉及**金额/税法结论必须由规则引擎或 KB 产出**;LLM 只把结果组织成自然语言。
- **把 LLM 输出当不可信**:每个工具调用按 schema 严格校验 + 类型化;**绝不把 LLM 原文直接喂给规则引擎/DB**。
- prompt 明确:"规则引擎是真相源;它拒绝就向用户解释原因,不得覆盖。"

## 3. 自己掌控 上下文 / prompt / 控制流（F2/F3/F8）
- **Own context(F3)**:RAG 检索由我们**预取 + 显式注入**(别让 LLM 自由决定检索什么);GraphRAG 命中带**法条/来源标签**返回,可审计。上下文是货币,精确控制。
- **Own prompts(F2)**:不依赖框架默认 prompt。
- **Own control flow(F8)**:自建显式状态机(何时查 KB、何时触发人工复核),不靠框架黑盒 loop → 防死循环/防跳过校验。

## 4. 工具 = 结构化输出;人工复核也是一个工具（F1/F4/F7）
- Skills 定义为**结构化输出**:`query_kb` / `calculate_income_tax`(调引擎) / `request_human_review`,严格 schema。
- **人在环 = 工具调用(F7)**:复杂/不可建模/高风险 → `request_human_review`(reason / severity / suggested_action),每次调用**审计日志**。对应产品原则"难例升级到(AI)人工支持"。

## 5. 小而专 + 无状态 reducer + 统一状态 + 错误压缩（F10/F12/F5/F9）
- **小而专 agent(F10)**:单 agent 限 3–20 步;复杂任务串成**确定性 DAG**(micro-agents),别造无所不能的巨型 agent。
- **无状态 reducer(F12)**:每次调用 = 纯函数 `(query, context, state) → 输出`,便于 replay/审计/测试(呼应引擎已是纯函数)。
- **统一状态(F5)**:单一 Thread/event log 记录 问题→KB检索→引擎结果→人工复核,防"agent 以为发生的"与"实际发生的"分叉。
- **错误压缩(F9)**:引擎/校验拒绝时,压成 1 行喂回 agent,不撑爆上下文。

## 6. 可评估 + 可观测（Anthropic measure everything / 计划 M4）
- 每个 Skill 有 **eval 用例**;金额类答案对 golden;trace 回流提升准确率(M4)。
- 关键分支 metrics + Error 日志(见 ARCHITECTURE.md / code_review_matrix §SRE),M2+ 全面生效。

## 7. 对我(Claude)当下也适用
- 多智能体 **review** 已在用 Anthropic 的 **parallelization**(并行 subagent 各管一个对抗视角)+ **evaluator-optimizer**(对抗验证)模式。
- 重大/高危 PR 用真并行 agent;小 PR 单脑——即"从简,按需加复杂度"。

> 落地时机:M2 起步时把本文件作为 Agent 层设计的硬约束;届时更新 ARCHITECTURE.md 的目标架构并解锁审查矩阵安全/性能/SRE 全项。
