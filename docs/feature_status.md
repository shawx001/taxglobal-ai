# TaxGlobal AI 功能状态总表（实时打勾 + 可溯源）

最后更新：2026-06-02（main @ `50c06af`）
维护规则：每个 step 的 PR 经 Claude review 通过 / 合并后，更新本表"状态"列。每行可追溯到 **设计文档 + 实现 commit + 官方来源**。

图例：✅ 已实现并测试 ｜ 🟡 已设计待实现 ｜ ⬜ 未开始

---

## A. 税务计算引擎函数（"算税的大脑"）

| 功能 | 状态 | Step | 设计文档 | 实现 commit | 官方来源 |
|---|---|---|---|---|---|
| `bracket_tax`（累进分档基础件） | ✅ | 2 | `step2_tax_engine.md` | `110376e` | — |
| `federal_income_tax`（联邦所得税） | ✅ | 2 | `step2_tax_engine.md` | `110376e` | Rev. Proc. 2024-40 |
| `fica_tax`（社保+医保+附加医保） | ✅ | 2 | `step2_tax_engine.md` | `110376e` | IRS Topic 751/560, Pub 15 |
| `feie_estimate`（海外收入豁免） | ✅ | 2 | `step2_tax_engine.md` | `110376e` | IRS FEIE / Form 2555 |
| `state_income_tax`（州所得税，无数据州拒算） | ✅ | 2 | `step2_tax_engine.md` | `110376e` | 各州 DOR |
| `self_employment_tax`（自雇税） | ✅ | 2.1 | `step2_1_design_se_nexus.md` | `e31deea` | IRS Pub 15-A, Topic 560 |
| `nexus_estimate`（电商经济联结预警） | ✅ | 2.1 | `step2_1_design_se_nexus.md` | `e31deea` | CDTFA / NY / TX / FL DOR |
| `crypto_gain_estimate`（加密成本基+资本利得税） | ✅ | 2.2 | `step2_2_design_crypto.md` | `1f98a60` | IRS Topic 409/559, Rev. Proc. 2024-40 |
| `rsu_tax_estimate`（RSU 归属税务） | ✅ | 2.3 | `step2_3_design_rsu.md` | `2e43a8e` | IRS §83, Rev. Proc. 2024-40 |
| `income_tax_summary`（多收入源合并计税） | ⬜ | 后续 | 待写 | — | — |

## B. 规则数据层（"大脑只信的真相源"）

| 数据文件 | 状态 | Step | 来源 | 备注 |
|---|---|---|---|---|
| `us_federal.json`（联邦档+标准扣除） | ✅ | 1 | Rev. Proc. 2024-40 | |
| `us_fica.json`（FICA/附加医保/自雇基数） | ✅ | 1 | IRS Topic 751/560, Pub 15/15-A | |
| `us_feie.json`（FEIE 上限/330天） | ✅ | 1 | IRS FEIE / Form 2555 | |
| `us_states.json`（10 州） | ✅ | 1 | 各州 DOR | CA/NY=待抽取，MA/TX=待来源 |
| `us_nexus.json`（经济联结阈值+`comparison`） | ✅ | 1 / 2.1 | CDTFA/NY/TX/FL | WA=待来源 |
| `us_capital_gains.json`（LTCG/STCG/NIIT） | ✅ | 1.1 | Rev. Proc. 2024-40, IRS Topic 409/559 | |
| `knowledge/us_core_knowledge.json`（知识候选） | ✅ | 1 | 同上 | 入库待 Step 6 |

## C. 工程基建

| 项 | 状态 | Step | 备注 |
|---|---|---|---|
| Git/目录/README/.gitattributes | ✅ | 0 | |
| 官方来源归档 + manifest + hash 强校验 | ✅ | 1 | raw 字节保全（跨平台 hash 稳定） |
| 黄金测试运行器（数据驱动） | ✅ | M3 | `tests/test_golden.py` |
| ruff + GitHub Actions CI | ✅ | M3 | ruff / unittest / 数据校验 三卡点 |
| 写码规范 + 评审清单 | ✅ | — | `coding_standards.md` / `code_review_checklist.md` |

## D. 后续大模块（未开始）

| 模块 | 状态 | Step |
|---|---|---|
| FastAPI 后端（`/calc/*`） | ⬜ | 4 |
| 前端改调后端 | ⬜ | 5 |
| 美国知识库 MVP | ⬜ | 6 |
| 知识库驱动提醒系统 | ⬜ | 7 |
| Copilot（检索+引擎+guardrail） | ⬜ | 8 |
| 持久化 + 审计日志（PostgreSQL） | ⬜ | 9 |
| 知识库定期更新 | ⬜ | 10 |
| 美国 MVP 完整联调 | ⬜ | 11 |

---

## 每步文档台账（可溯源：设计 + 交付）

| Step | 设计文档（动手前） | 交付记录（做完后） |
|---|---|---|
| 0 工程基线 | — | `step0_engineering_baseline.md` |
| 1 规则数据层 | — | `step1_tax_rule_data.md` |
| 2 计算引擎 | — | `step2_tax_engine.md` |
| 2.1 SE+Nexus | `step2_1_design_se_nexus.md` | `step2_1_se_nexus_engine.md` |
| 3 黄金测试+CI（曾称 M3） | `step3_design_golden_tests.md` | `step3_golden_tests.md` |
| 1.1 资本利得数据 | `step1_1_design_capital_gains.md` | `step1_1_capital_gains_data.md` |
| 2.2 加密计算 | `step2_2_design_crypto.md` | `step2_2_crypto_engine.md` |
| 2.3 RSU | `step2_3_design_rsu.md` | `step2_3_rsu_engine.md` |

流程/标准类：`engineering_process.md`、`phase1_define_us_mvp.md`、`coding_standards.md`、`code_review_checklist.md`、`feature_status.md`（本文件）。

> 注：Step 0–2 当时未单独出"设计文档"（直接在交付记录里写了目标/验收）；从 2.1 起每步都有独立设计文档。今后所有 step 一律「设计文档 → 实现 → 交付记录 + 更新本表」。
