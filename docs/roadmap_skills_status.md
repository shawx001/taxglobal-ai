# 路线图与 18 Skills 现状映射

> 目的:让"我们现在在哪、18 Skills 做到哪"始终可见,不再"看不到"。
> 依据:`TaxGlobal_AI_项目计划书_v3.1.md`(M0–M5 里程碑 + 18 Skills 架构)。
> 维护:每完成一步由 Claude 更新本表 + `feature_status.md`。最后更新:2026-06-03。

## 一、里程碑路线图(M0–M5)与当前位置

| 里程碑 | 周期 | 交付 | 状态 |
|---|---|---|---|
| **M0 原型** | — | 高保真可交互原型,全流程可点可算 | ✅ 已完成 |
| **M1 引擎硬化** | 第 1–3 周 | tax-engine 后端服务 + 黄金测试集 + CI;前后端结果一致 | ✅ **收尾完成** |
| **M2 Agent + 知识层** | 第 3–5 周 | **18 Skills**(LangChain 编排)+ GraphRAG(MVP) | 🔲 未开始(依赖 M1 + KB) |
| **M3 连接器 + 多模态** | 第 5–7 周 | OAuth、Shopify/Amazon 真连、Qwen-VL W-2 识别、自有 Copilot 模型 | 🔲 未开始 |
| **M4 训练闭环** | 第 7–8 周 | Trace 回流 + LoRA + Eval Harness | 🔲 未开始 |
| **M5 合规与上线** | 第 9–10 周 | 安全/合规/可观测 + Demo 联调 | 🔲 未开始 |

**M1 收尾状态**:REQ-009 引擎三块已齐(Block 1/2/3 已合并);REQ-002 前端总览已接到单次 `income_tax_summary`。下一阶段进入 M2 Skills/Agent + 知识层。

## 二、18 Skills 清单与现状

**关键澄清**:这里的"Skills"是**计划书里 LangChain Agent Runtime 编排的应用层技能**(M2),**不是** Claude Code 的 `/skill`。每个 Skill 涉及金额的输出必须来自**规则引擎**,自有模型不得编造数字(计划书 Guardrail)。

计划书 v3.1 §九点名了 11 个(原文以"等"结尾,共 18 个;未点名的 7 个待 M2 启动时补全,**此处不臆造**)。计算内核(引擎函数)现状:

| # | Skill | 依赖的引擎函数/能力 | 引擎内核状态 |
|---|---|---|---|
| 1 | `calculate_income_tax` | `income_tax_summary`(W-2/自雇/资本利得/NIIT/FEIE 三块) | ✅ 已完成 |
| 2 | `assess_feie` | `feie_estimate` | ✅ 已完成 |
| 3 | `analyze_rsu` | `rsu_tax_estimate` | ✅ 已完成 |
| 4 | `track_crypto` | `crypto_gain_estimate` + `_crypto_state_tax` | ✅ 已完成 |
| 5 | `detect_nexus` | `nexus_estimate`(经济联结 Wayfair) | ✅ 已完成 |
| 6 | `parse_profile` | 档案解析/编排(= REQ-002 前端总览入口) | ✅ 可用(REQ-002 前端总览) |
| 7 | `classify_transaction` | 交易分类(加密/电商品类),待 KB/规则 | 🔲 待 M2 |
| 8 | `rank_nomad_cities` | 数字游民城市排名,待数据/规则 | 🔲 待 M2 |
| 9 | `extract_w2` | Qwen-VL W-2 识别(多模态) | 🔲 待 M3 |
| 10 | `generate_form` | 表单生成(1040 等) | 🔲 待 M2/M3 |
| 11 | `check_treaty` | 税收协定/FTC(关联 REQ-004 海外被动收入) | 🔲 待 M2+ |
| 12–18 | (计划书未点名,TBD) | 待 M2 启动时枚举 | 🔲 待定义 |

**小结**:18 个中已点名 11 个;其中 **5 个 Skill 的权威计算内核已在引擎里就绪**(calculate_income_tax / assess_feie / analyze_rsu / track_crypto / detect_nexus)——M2 主要是把这些引擎函数封成 LangChain Skill(薄封装 + guardrail)并接 GraphRAG,而非重写计算。

## 三、为什么 Skills 还没动(诚实说明)
1. **顺序使然**:Skills 是 Agent 编排层(M2),需调用底层规则引擎(M1)+ 知识库(GraphRAG)。引擎未夯完、KB 未建,Agent 层无从编排。计划本就把它排在引擎之后。
2. **可见性缺口(已修)**:此前埋头引擎分块,未维护 Skills/里程碑视图;本文件 + 记忆补上,之后每步更新。

## 四、决定(2026-06-03)
Shaw 选择**先收尾引擎 + 前端**:REQ-002 前端总览已完成 M1 收尾，之后进入 M2 的 Skills/Agent 层。
