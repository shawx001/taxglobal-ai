# M4 训练闭环 + 连接器 —— 分步计划

> 目的：把 M4（训练闭环 + 电商连接器）拆成可独立交付、可测试、CI 绿的小步。
> 依据：`TaxGlobal_AI_项目计划书_v3.1.md` §6.6 训练闭环（Trace→SFT/LoRA→Eval→回流，
> Qwen2.5-0.5B + LoRA「CPU 可跑」）+ §6.4 连接器（统一 OAuth 跳转）；
> 与 `docs/agent_architecture_principles.md`（规则引擎=唯一真相、LLM 不可信、人工复核=工具）一致。
> 维护：每完成一步由 Claude 更新本表 + `feature_status.md` + `roadmap_skills_status.md`。

## 范围与「可自建 vs 卡外部依赖」的诚实划线

M4 大部分**本地可自建**；少数环节的**真实运行**卡在外部依赖（算力 / Shaw 的 OAuth 凭据 / API key），
对这些环节做到「脚手架 + sandbox/mock + 测试」的可插拔边界，给到凭据/算力即可跑。

| 环节 | 可自建部分 | 卡外部依赖（真实运行）|
|---|---|---|
| Eval Harness | ✅ 全部（离线确定性，CI 跑）| 无 |
| Trace→SFT 数据管道 | ✅ 全部（审计日志/文件双源 → 质量筛选 → JSONL）| 真实 trace 量需线上流量 |
| LoRA 训练管道 | ✅ 脚本+配置+数据准备+eval 门禁集成；小数据 CPU smoke | 真实微调需算力 + HF 模型下载（网络）|
| 连接器（Shopify/Amazon/OAuth）| ✅ 框架+归一化适配器+sandbox 数据+OAuth 跳转脚手架+测试 | 真实连接需 Shaw 注册的 OAuth 应用与凭据 |

## 步骤

### M4.1 Eval Harness ✅（PR #90）
- **目标**：统一评测「模型面向」质量并产出总分 + ≥0.80 部署门禁（计划书 §6.6）。
- **维度**（离线确定性，无需真实 LLM，CI 可跑）：
  1. 意图分类准确率（复用 50 例 labeled set；harness 接受任意 classifier，默认关键词基线，
     评测 LoRA 时传模型 classifier）。
  2. Fact-check 保真度（labeled set：模型 answer_text × 引擎 answer → 预期 verdict），
     兼作 fact-checker 回归守门。
- **交付**：`backend/eval/{datasets,harness}.py`、`scripts/eval_harness.py`（→ `docs/eval/eval_report.json`，
  门禁不过 exit≠0）、`tests/test_m4_1_eval_harness.py`。`scripts/eval_intent_accuracy.py` 改为复用
  `backend.eval.datasets.INTENT_TESTSET`（DRY）。
- **说明**：引擎正确性由 `tests/golden/*.json` 单独保证（确定性规则码，非模型），不计入「模型质量」总分；
  门禁用于 LoRA 模型上线，而非关键词基线（基线可能低于 0.80，属正常）。

### M4.2 Trace→SFT 数据管道 ✅（本步）
- 审计日志（M2.9 `AuditLog`，PII 已脱敏）+ 文件 trace 双源 → 质量筛选（fact-check 通过、有引用、
  非 clarify 兜底）→ SFT JSONL（{messages:[...]} 或 {prompt,completion}）。新旧混合比例（新 20%/历史 80%）。
- 交付：`backend/training/trace_export.py` + CLI + 测试（用合成 trace，不依赖 PG）。

### M4.3 LoRA 训练管道（Qwen2.5-0.5B，CPU 可跑）
- HuggingFace PEFT + TRL：数据准备 → LoRA 增量微调（1 epoch）→ 调 M4.1 harness 做 ≥0.80 门禁 → 产出 adapter。
- 新增依赖：`torch/peft/trl/datasets`（pin）。提供极小数据 CPU smoke test；真实微调需算力 + HF 下载。
- 交付：`backend/training/lora_finetune.py` + 配置 + smoke 测试 + 文档化算力/下载依赖。

### M4.4 连接器框架 + sandbox 适配器
- 统一抽象 `{platform, facilitator, salesByState, txns}`，对接既有 `nexus_estimate` 引擎；
  OAuth 跳转脚手架（授权 URL→回调→换 token 的接口，sandbox 模式返回样例数据）。
- Shopify / Amazon SP-API 适配器（sandbox/mock）+ 测试；真实连接待 Shaw 提供 OAuth 凭据。
- 交付：`backend/connectors/` + 路由 + 测试。

## 验收门禁（每步）
```
python -m unittest discover -s tests
python -m ruff check engine backend tests
powershell -ExecutionPolicy Bypass -File tests/validate_step1_data.ps1
git diff --check
```
+ 每 PR CI 全绿才合并、Copilot 粗审处理。
