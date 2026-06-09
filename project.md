# PROJECT.md — TaxGlobal AI 实时工作状态(续接入口)

> 用途:上下文丢失也能无缝续接。**新对话先读本文件**,再按需读下方"续接读取顺序"。
> 维护:每完成一步由 Claude 更新本文件的"当前进度 / 下一步"。最后更新:2026-06-08（M2 启动）。

## 0. 一句话
US-first 报税计算/合规 MVP,真实上线导向(高并发、极敏 PII、外部 LLM 语言层 + 金额不经 LLM、税季尖峰)。**#1 原则:数值精确到分 + 税率只来自版本化数据 + 可溯官方源。**

## 1. 里程碑(详见 `docs/roadmap_skills_status.md`)
- **M0 原型** ✅ · **M1 引擎硬化** ✅ **已完成并正式关闭（2026-06-07）** · **M2 Agent+知识层** 🔲 下一阶段 · M3 连接器/多模态 · M4 训练闭环 · M5 合规上线。

## 2. 引擎现状(M1 成果)
- **模块化包** `engine/`:`money / responses / filing / brackets / dates / federal / payroll / qbi / feie / state / crypto / rsu / nexus / summary` + `__init__`(公共门面)+ `tax_engine.py`(legacy shim)+ `rules_loader`。
- **税年数据** `data/tax_years/2025/` 与 `2026/`;**默认 tax_year=2026**(2025 保留,可传参回溯)。每数可溯(source_manifest + 归档原件)。
- **`income_tax_summary`**(合并计税):W-2 + 自雇(共享SS基数/合并AddlMedicare)+ 其它普通 + 短/长期资本利得(QDCGT 叠加)+ QBI(§199A,含 2026 phase-in)+ NIIT(含 FEIE 加回)+ **FEIE 税率叠加(对普通税与资本利得都垫底)** + 州税。
- **州覆盖(51 effective — 50 州 + DC 全覆盖 ✅)**:28 progressive(AL/AR/CA/CT/DC/DE/HI/KS/MD/ME/MN/MO/MS/MT/ND/NE/NJ/NM/NY/OH/OK/OR/RI/SC/VA/VT/WI/WV)+ 14 flat(AZ/CO/GA/IA/ID/IL/IN/KY/LA/MA/MI/NC/PA/UT)+ 9 none(AK/FL/NH/NV/SD/TN/TX/WA/WY)。特殊机制:MA 4% surtax、AL/OR federal tax subtraction、WA capital gains excise、NJ gross-income+门槛+免税额、PA 3.07% gross。
- 其它引擎函数:`federal_income_tax / fica_tax / self_employment_tax / qbi_deduction / feie_estimate / state_income_tax / crypto_gain_estimate / rsu_tax_estimate / nexus_estimate`。
- **前端**:`frontend/index.html`(vanilla SPA)——profile 单一真相源(localStorage)+ 合并总览一次调 `/calc/income-summary`;根 `index.html` 冻结。

## 3. 当前进度 / 下一步
- **M1 正式关闭（2026-06-07）**:PR #40 deepcopy→freeze 优化已合并；PR #41 前端 50 州+DC 动态下拉已合并；PR #43 文档更新。
- **州覆盖**:51 effective = 28 progressive + 14 flat + 9 none。全部 50 州 + DC 完成。
- **50 州计划**:`docs/step_c_all_states_plan.md` 所有批次 C1–C4 完成。
- **当前**:→ **M2（Agent + 知识层）已启动**。技术栈:Neo4j(图谱) + Chroma(向量) + sentence-transformers(本地 embedding) + LangChain/LangGraph(编排) + PostgreSQL(业务)。步骤计划见 `docs/m2_step_plan.md`(10 步,当前 M2.1)。

## 4. 协作 & 规则(详见 `/AGENTS.md`)
- 分工:**Shaw** 拍板;**Codex** 主实现+开 PR;**Claude** 规划/设计文档/逐行 review + **独立逐分重算** + 官方源交叉核 + 多智能体审查矩阵 + **review 通过无问题直接 merge**。
- 铁律:数值到分、规则=数据(永不裸写)、新州/年=只改数据、no-monolith 模块化、无状态+幂等、防御性输入、PII 脱敏后才发外部 LLM(金额不经 LLM)、不自我认证→硬门禁、**写码即带工业级 sense 不靠 review 纠错**、一步一 PR。
- 审查节奏:完整多 agent 会审**每大 block 一次**;小任务单条 review。审查矩阵见 `docs/code_review_matrix.md`(含税务专家 + 以 `/ARCHITECTURE.md` 为抗压边界去幻觉)。

## 5. 续接读取顺序(新对话)
1. 本文件(project.md)→ 2. `/AGENTS.md`(铁律)→ 3. `/ARCHITECTURE.md`(抗压边界)→ 4. `docs/feature_status.md` + `docs/roadmap_skills_status.md`(进度/Skills)→ 5. `docs/code_review_matrix.md` + `docs/agent_architecture_principles.md`(review/M2)→ 6. 当前步的 `docs/*_design_*.md`。

## 6. 环境 & 门禁(开 PR 前全绿)
- Python:`C:\Users\shawx\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`;`PYTHONPATH=<repo root>`。
- 门禁:`python -m unittest discover -s tests` · `python -m ruff check engine backend tests` · `powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1` · `git diff --check` · 两份 index.html hash 不变 · CI 绿。
- review 用 worktree:`git worktree add <tmp> pr<N>-review`(独立隔离,审完移除)。
