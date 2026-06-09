# M2 Step Plan — Agent + Knowledge Layer

> 目标:把 M1 的纯计算引擎升级为可对话、有知识、有记忆的税务助手基础设施。
> 周期:第 3-5 周(约 10 个工作日)。
> 原则:workflow > agent 默认；规则引擎 = 唯一真相；LLM 输出不可信；小步可测；一步一 PR。
> 依据:`ARCHITECTURE.md` §3 + `docs/agent_architecture_principles.md` + `docs/roadmap_skills_status.md`。
> 维护:每步完成后打勾 + 更新 `project.md` + `feature_status.md`。

---

## 大白话:M2 做完能干嘛 + 验收标准

### 三个数据库分别存什么

| 数据库 | 存什么 | 一句话 |
|---|---|---|
| **PostgreSQL** | 用户档案(收入/州/报税身份) + 审计日志(谁算了什么) | 存用户的东西,合规可查 |
| **Neo4j** | 税法知识的关系网:规则→州→来源→话题,沿链找相关知识 | 存知识的"关系" |
| **Chroma** | 每条知识的语义向量,"海外收入豁免"能匹配到"FEIE" | 存知识的"意思" |

### M2 做完用户能做什么(对比 M1)

| 功能 | M1(现在) | M2 做完后 |
|---|---|---|
| 算税 | 手动填数字 → 出结果 | **不变**,原来的计算器照常 |
| 保存档案 | 只存浏览器,换电脑就没了 | 存服务器,跨设备都能读 |
| 问问题 | 没有 | 输入"加州收入15万交多少税" → 自动调引擎 → 返回结果+法条来源 |
| 搜知识 | 没有 | 搜"FEIE是什么" → 返回解释+IRS来源 |
| 个性化提醒 | 没有 | 根据档案推:"你是自雇,别忘6/15预估税"、"MA收入超100万,注意4%附加税" |
| 审计追踪 | 没有 | 每次计算/查询都有记录,合规可查 |

### 诚实说明

M2 **没有真正的"AI 对话"**。自部署 Qwen 模型是 M3 才接入的。M2 的"问问题"本质是关键词匹配→调计算器或查知识库→模板拼结果。真正的"打字问问题,AI 用人话回答"要到 M3。

M2 核心价值:①搭好基础设施(三库+知识+Skill+安全) ②实打实的功能(档案保存+提醒+知识搜索) ③给 M3 AI 对话铺路(接入 Qwen 后一切就活了)。

### 验收标准(M2 怎么算通过)

1. ✅ 输入"加州收入15万" → 返回正确州税金额 + "来源:CA FTB"(到分准确)
2. ✅ 搜"FEIE" → 返回 FEIE 解释 + IRS Form 2555 来源
3. ✅ 保存档案 → 关浏览器 → 重新打开 → 档案还在
4. ✅ 自雇用户看到"6/15 预估税截止"提醒
5. ✅ 所有操作有审计日志,SSN 等敏感信息已脱敏
6. ✅ 伪造金额被 Guardrail 拦截(不会编造税额)
7. ✅ 三个数据库全挂 → `/calc/*` 计算器照常工作(向后兼容)

---

## 技术栈决策(2026-06-08 Shaw 拍板)

| 层 | 技术 | 说明 |
|---|---|---|
| **知识图谱** | **Neo4j** | 税法实体关系网(规则↔州↔话题↔来源);Cypher 查询 |
| **向量库** | **Chroma**(MVP) / Milvus(扩容) | 语义相似度检索;嵌入后持久化 |
| **Embedding** | **sentence-transformers** 本地推理 | `BAAI/bge-small-zh-v1.5`(中英双语,24M);CPU 可跑;数据不出境 |
| **编排框架** | **LangChain + LangGraph** | Skill = LangChain Tool;LangGraph 做 workflow 状态机 |
| **业务数据库** | **PostgreSQL 16** | profiles / audit_log;SQLAlchemy 2.0 + Alembic |
| **Schema 校验** | **Pydantic v2** | 输入/输出严格校验 |
| **LLM(M2 阶段)** | **暂无 / mock** | M2 编排器用确定性路由;M3 接入自部署 Qwen + vLLM |

```
┌─────────────────────────────────────────────────┐
│                  前端 (vanilla SPA)               │
│           localStorage → API calls               │
└────────────────────┬────────────────────────────┘
                     │ HTTP
┌────────────────────▼────────────────────────────┐
│              FastAPI 后端                         │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ /calc/*  │  │ /api/*   │  │ /api/assistant│  │
│  │ (M1引擎) │  │ profiles │  │ (编排器入口)  │  │
│  └────┬─────┘  └────┬─────┘  └───────┬───────┘  │
│       │             │                │           │
│  ┌────▼─────────────▼────────────────▼────────┐  │
│  │          LangGraph Workflow 编排器           │  │
│  │  意图分类 → Skill/KB 路由 → Guardrail →    │  │
│  │  响应组装                                   │  │
│  └──┬──────────┬──────────────┬──────────────┘  │
│     │          │              │                  │
│  ┌──▼───┐  ┌──▼──────┐  ┌───▼────────────┐     │
│  │Skills│  │Guardrail│  │  KB 检索       │     │
│  │(Tool)│  │ 中间件  │  │(GraphRAG)     │     │
│  └──┬───┘  └─────────┘  └─┬─────────┬───┘     │
│     │                      │         │          │
└─────┼──────────────────────┼─────────┼──────────┘
      │                      │         │
┌─────▼─────┐  ┌─────────────▼───┐  ┌──▼──────────┐
│  engine/  │  │    Neo4j        │  │   Chroma     │
│ 纯函数    │  │  知识图谱       │  │  向量库      │
│ (M1不变)  │  │  (实体+关系)    │  │ (embeddings) │
└───────────┘  └─────────────────┘  └──────────────┘
                                    ↑
                              sentence-transformers
                              bge-small-zh-v1.5(本地)
      ┌───────────┐
      │PostgreSQL │  profiles / audit_log
      └───────────┘
```

---

## M2 前提(M1 已就绪)

| 资产 | 状态 |
|---|---|
| 计算引擎(模块化 `engine/` 包) | ✅ 纯函数 + Decimal + 51 jurisdictions |
| FastAPI 后端(`/calc/*` + `/api/states`) | ✅ 无状态 |
| 规则数据(`data/tax_years/2025+2026/`) | ✅ 冻结缓存(MappingProxyType) |
| 5 个 Skill 引擎内核 | ✅ income_tax_summary / feie / rsu / crypto / nexus |
| 知识候选数据 `knowledge/us_core_knowledge.json` | ✅ 待结构化入库 |
| 前端 SPA(vanilla) | ✅ localStorage 档案 + 动态州下拉 |
| CI(unittest + ruff + data validation) | ✅ |

---

## Step 总览

| Step | 标题 | 产出 | 依赖 | 状态 |
|---|---|---|---|---|
| M2.1 | 三库基础设施 | PostgreSQL + Neo4j + Chroma + embedding 模型 | — | ✅ PR #45 merged 2026-06-08 |
| M2.2 | 知识图谱建模 + 数据入库 | Neo4j schema + Chroma embeddings + 入库脚本 | M2.1 | ✅ PR #47 merged 2026-06-08 |
| M2.3 | GraphRAG 检索 API | `GET /api/knowledge/search`(图+向量混合) | M2.2 | ✅ PR #49 merged 2026-06-08 |
| M2.4 | 档案持久化 API | `POST/GET /api/profiles` | M2.1(PG) | ✅ PR #51 merged 2026-06-08 |
| M2.5 | LangChain Skill 框架 + 5 引擎 Skills | LangChain Tool 封装 + 注册表 | — | ✅ PR #53 merged 2026-06-08 |
| M2.6 | Guardrail 中间件 | 金额来源验证 + schema 校验 + 升级钩子 | M2.5 | ✅ PR #55 merged 2026-06-09 |
| M2.7 | LangGraph Workflow 编排器 | 意图路由 → KB + Skill 调度 → 结构化响应 | M2.3, M2.5, M2.6 | ✅ PR #57 merged 2026-06-09 |
| M2.8 | KB 驱动税务提醒 + 截止日 | `GET /api/tips` + 档案关联提醒 | M2.3, M2.4 | ✅ PR #59 merged 2026-06-08 |
| M2.9 | 审计日志 | 全链路追踪:计算/查询/档案访问 + PII 脱敏 | M2.1(PG) | 🟡 PR #61 open |
| M2.10 | 集成测试 + M2 关闭 | 端到端验证 + 文档更新 | 全部 | ⬜ |

```
依赖图:

M2.1(三库) ──┬── M2.2(图谱+向量入库) ── M2.3(GraphRAG API) ──┐
              ├── M2.4(档案 API) ────────────────────────────┤
              └── M2.9(审计日志)                               │
                                                               ├── M2.7(LangGraph 编排) ── M2.10
M2.5(LangChain Skills) ── M2.6(Guardrail) ───────────────────┤
                                                               │
                                                 M2.8(提醒) ──┘

可并行:M2.1 与 M2.5 无依赖,可同时开工。
M2.4 与 M2.2/M2.3 可并行(只依赖 PG,不依赖 Neo4j/Chroma)。
```

---

## 各步详细设计

### M2.1: 三库基础设施

**目标**:搭建 PostgreSQL + Neo4j + Chroma 三套存储 + 本地 embedding 模型。

**新增依赖**(在 `requirements.txt` 或 `pyproject.toml`):
```
# PostgreSQL
sqlalchemy[asyncio]>=2.0
alembic
asyncpg

# Neo4j
neo4j>=5.0

# Chroma (向量库)
chromadb>=0.4

# Embedding (本地)
sentence-transformers>=2.2

# LangChain (M2.5 开始用,但依赖先装)
langchain-core>=0.2
langchain-community>=0.2
langgraph>=0.1
```

**改动**:

#### A. PostgreSQL + Alembic
- 新增 `backend/database.py`:连接池 + Session 工厂
- 新增 `backend/config.py`:环境变量(`DATABASE_URL`, `NEO4J_URI`, `CHROMA_PATH`)
- 新增 `alembic/` 目录 + 初始迁移:
  ```sql
  CREATE TABLE users (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );

  CREATE TABLE profiles (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL REFERENCES users(id),
      tax_year INT NOT NULL DEFAULT 2026,
      data JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id, tax_year)
  );

  CREATE TABLE audit_log (
      id BIGSERIAL PRIMARY KEY,
      request_id UUID NOT NULL,
      user_id UUID,
      action VARCHAR(50) NOT NULL,
      input JSONB,
      output JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  CREATE INDEX idx_audit_request ON audit_log(request_id);
  CREATE INDEX idx_audit_user ON audit_log(user_id);
  ```

#### B. Neo4j 连接
- 新增 `backend/knowledge/neo4j_client.py`:
  - `get_driver()`:Neo4j driver 单例
  - `run_query(cypher, params)`:执行 Cypher 查询
  - 启动时验证连接 + 创建约束/索引

#### C. Chroma + Embedding
- 新增 `backend/knowledge/vector_store.py`:
  - Chroma 持久化目录:`data/chroma/`
  - Collection 名:`tax_knowledge`
- 新增 `backend/knowledge/embedder.py`:
  - 加载 `BAAI/bge-small-zh-v1.5`(首次自动下载到 `~/.cache/`)
  - `embed_text(text) -> list[float]`:单条文本 → 384 维向量
  - `embed_batch(texts) -> list[list[float]]`:批量嵌入
- 模型缓存:应用启动时加载一次,后续复用

#### D. 更新 `backend/main.py`
- app startup:初始化 PG 连接池 + Neo4j driver + Chroma client + 加载 embedding 模型
- app shutdown:关闭连接
- **向后兼容**:任何存储不可用时 `/calc/*` 仍正常(graceful degradation)

**测试**:
- `test_pg_connection`:PostgreSQL 连接成功 + 表存在
- `test_neo4j_connection`:Neo4j 连接成功
- `test_chroma_collection`:Chroma collection 可读写
- `test_embedding_model`:嵌入文本返回 384 维向量
- `test_calc_api_without_db`:DB 全关 → `/calc/income-tax` 仍返回正确结果

**验收门禁**:全部 test 绿 + ruff clean + 现有 M1 API 不受影响。

---

### M2.2: 知识图谱建模 + 数据入库

**目标**:设计 Neo4j 图谱 schema,把知识数据同时入库到 Neo4j(实体关系)和 Chroma(向量)。

**Neo4j 图谱 Schema**:
```
节点类型:
  (:TaxRule {id, title, content, tax_year, source_id, rule_type})
  (:Jurisdiction {code, name, type})   -- 'federal' / 'CA' / 'NY' / ...
  (:Topic {name})                      -- 'deductions' / 'credits' / 'deadlines' / ...
  (:Source {id, name, url})            -- 'IRS Rev.Proc. 2024-40' / 'CA FTB'
  (:Deadline {date, title, applies_to})

关系:
  (:TaxRule)-[:APPLIES_TO]->(:Jurisdiction)
  (:TaxRule)-[:ABOUT]->(:Topic)
  (:TaxRule)-[:CITED_FROM]->(:Source)
  (:TaxRule)-[:SUPERSEDES]->(:TaxRule)        -- 跨税年版本链
  (:Deadline)-[:FOR]->(:Jurisdiction)
  (:Jurisdiction)-[:HAS_SURTAX]->(:TaxRule)   -- 州特殊机制
```

**知识数据扩充**(扩展 `knowledge/us_core_knowledge.json`):
- **联邦核心**(~30 条):标准扣除、SALT cap、慈善扣除、学生贷款利息、IRA、QBI §199A、AMT、EITC、Child Tax Credit、NIIT
- **截止日**(~10 条):4/15, 6/15, 9/15, 1/15, 10/15, W-2 发放截止(1/31), 1099 截止
- **FEIE/FTC**(~5 条):330 天测试、bona fide residence、FTC 基础概念
- **州级 gotchas**(~15 条):MA 4% surtax、NJ gross-income 门槛、WA capital gains excise、OR federal subtraction、CA itemized vs standard、NY city tax
- **数字游民**(~5 条):state residency rules、nexus triggers、multi-state filing
- **加密**(~5 条):wash sale(待定)、cost basis methods、holding period、1099-DA
- 每条必须有 `source_id`

**入库脚本**:
- 新增 `backend/knowledge/ingestion.py`:
  - `ingest_to_neo4j(data)`:创建节点 + 关系(MERGE 幂等)
  - `ingest_to_chroma(data)`:文本 → embedding → upsert 到 Chroma
  - `ingest_all()`:一次性入库到两个存储
- CLI:`python -m backend.knowledge.ingestion`

**测试**:
- `test_neo4j_nodes_created`:入库后节点数 > 0
- `test_neo4j_relationships`:TaxRule→Jurisdiction 关系存在
- `test_chroma_documents`:Chroma 文档数与知识条目数一致
- `test_ingestion_idempotent`:重复执行不创建重复
- `test_every_entry_has_source`:source_id 非空

**数据量目标**:MVP ~70 条高质量条目。

---

### M2.3: GraphRAG 检索 API

**目标**:实现"图查询 + 向量相似度"混合检索,提供统一搜索接口。

**检索策略**:
```
用户查询 "FEIE 330天测试"
  │
  ├─① 向量检索(Chroma):语义相似度 top-K
  │   → "FEIE 基本概念", "330-Day Test 要求", "Bona Fide Residence"
  │
  ├─② 图查询(Neo4j):从匹配节点沿关系展开
  │   → TaxRule→CITED_FROM→Source (找到 IRS Form 2555)
  │   → TaxRule→APPLIES_TO→Jurisdiction (找到 federal)
  │   → TaxRule→ABOUT→Topic (找到 foreign_income)
  │
  └─③ 合并 + 排序 + 去重
      → 综合 relevance_score = α×向量分 + β×图分
      → 每条附带 source citation + 关联实体
```

**改动**:
- 新增 `backend/knowledge/search.py`:
  - `vector_search(query, top_k=5)`:Chroma 语义检索
  - `graph_search(entity_ids)`:Neo4j 关系展开
  - `hybrid_search(query, filters)`:混合检索 + 排序
- 新增路由:
  ```
  GET /api/knowledge/search?q=FEIE&jurisdiction=federal&topic=foreign_income&tax_year=2026
  Response: {
    "results": [
      {
        "id": "...",
        "title": "Foreign Earned Income Exclusion (FEIE)",
        "content": "...",
        "source": { "id": "IRS Form 2555", "name": "IRS", "url": "..." },
        "jurisdiction": "federal",
        "topics": ["foreign_income", "exclusion"],
        "related": ["Bona Fide Residence Test", "Physical Presence Test"],
        "relevance_score": 0.95,
        "retrieval_method": "hybrid"  // "vector" / "graph" / "hybrid"
      }
    ],
    "total": 3,
    "query_metadata": { "vector_hits": 5, "graph_expansions": 3 }
  }
  ```

**测试**:
- `test_vector_search`:语义搜索 "海外收入豁免" 命中 FEIE 相关条目
- `test_graph_search`:从 FEIE 节点展开找到 IRS Source + federal Jurisdiction
- `test_hybrid_outperforms_vector_only`:混合检索比纯向量多返回关联条目
- `test_filter_by_jurisdiction`:jurisdiction=CA 只返回 CA + federal
- `test_source_citation_always_present`:每条结果有 source
- `test_empty_result`:不匹配 → 空列表(不报错)

---

### M2.4: 档案持久化 API

**目标**:用户档案从 localStorage 迁移到服务端(PostgreSQL),支持跨设备 + 审计。

**改动**:
- 新增 `backend/profiles/` 包:
  - `models.py`:Profile SQLAlchemy ORM
  - `schemas.py`:Pydantic 输入/输出 schema(与前端 localStorage 结构对齐)
  - `routes.py`:CRUD 路由
- 新增路由:
  ```
  POST /api/profiles          → 创建/更新档案(upsert by user_id + tax_year)
  GET  /api/profiles/{id}     → 读取档案
  GET  /api/profiles?user_id=...&tax_year=2026  → 按用户+税年查
  ```
- 幂等:相同 user_id + tax_year 重复 POST → update(不创建重复)
- **PII 注意**:MVP 阶段 data 字段存 JSONB 明文;M5 加列级加密。schema 注释标注 PII 字段。
- 前端适配:`api.js` 新增 profile save/load;页面切换时自动同步

**测试**:
- `test_profile_create_and_read`:创建后读回一致
- `test_profile_upsert`:重复 POST 同 user+year → 更新(不新建)
- `test_profile_not_found`:不存在 → 404
- `test_profile_validation`:缺必填 → 422

---

### M2.5: LangChain Skill 框架 + 5 引擎 Skills

**目标**:用 LangChain Tool 接口封装 5 个引擎函数,注册到统一 Skill 注册表。

**改动**:
- 新增 `backend/skills/` 包:
  - `base.py`:基于 LangChain `BaseTool` 的 Skill 基类
    ```python
    from langchain_core.tools import BaseTool
    from pydantic import BaseModel

    class TaxSkill(BaseTool):
        """Base class for all tax calculation skills."""
        source_attribution: str    # 引擎来源标识
        guardrail_enabled: bool = True

        def _run(self, **kwargs) -> dict:
            """Validate input → call engine → validate output → return."""
            validated = self._validate_input(kwargs)
            result = self._execute_engine(validated)
            self._validate_output(result)
            return result

        @abstractmethod
        def _execute_engine(self, params: dict) -> dict:
            """Call the underlying engine pure function."""
    ```
  - `registry.py`:注册表(name → TaxSkill 实例)+ `get_all_tools() -> list[BaseTool]`
  - `calculate_income_tax.py`:封装 `income_tax_summary`
  - `assess_feie.py`:封装 `feie_estimate`
  - `analyze_rsu.py`:封装 `rsu_tax_estimate`
  - `track_crypto.py`:封装 `crypto_gain_estimate`
  - `detect_nexus.py`:封装 `nexus_estimate`
- 新增路由:
  ```
  GET  /api/skills            → 列出所有 Skills(name + description + input schema)
  POST /api/skills/{name}     → 调用指定 Skill
  ```
- 每个 Skill:
  - Pydantic model 定义 input/output schema
  - 调用 `engine/` 纯函数
  - 输出标准化(金额用 str 精确表示 + source attribution)
  - 引擎异常不捕获(let it fail loudly → 422)

**测试**:
- `test_skill_registry`:5 个 Skill 已注册
- `test_langchain_tool_interface`:每个 Skill 是合法的 LangChain Tool
- `test_skill_input_validation`:错误输入 → ValidationError
- `test_skill_output_matches_engine`:Skill 输出与直接调引擎一致(到分)
- `test_skill_list_endpoint`:GET /api/skills 返回 5 个

---

### M2.6: Guardrail 中间件

**目标**:确保涉及金额的输出只来自规则引擎,LLM/外部输出不可信。

**改动**:
- 新增 `backend/guardrail/` 包:
  - `validator.py`:
    - `validate_amount_source(result, engine_trace)`:金额字段必须有引擎调用 trace
    - `validate_schema(data, schema)`:Pydantic 严格校验
    - `check_coverage(jurisdiction, topic)`:引擎是否覆盖
  - `escalation.py`:
    - `EscalationLevel` enum:INFO / WARNING / NEEDS_REVIEW / BLOCKED
    - `request_human_review(reason, severity, context)`:写审计日志 + 返回升级标记
  - `middleware.py`:FastAPI 依赖注入,拦截 Skill/编排器输出做检查
- 规则:
  1. 金额字段(`*_tax`, `*_amount`, `*_deduction`, `total_*`)必须匹配引擎调用
  2. `not_covered` 不可被覆盖为确定数字
  3. 超出覆盖范围 → `NEEDS_REVIEW`
  4. 后续 LLM 输出中的数字必须与 Skill 结果交叉验证

**测试**:
- `test_guardrail_blocks_fabricated_amount`:伪造金额 → 拦截
- `test_guardrail_passes_engine_amount`:引擎产出 → 通过
- `test_not_covered_preserved`:not_covered 不被覆盖
- `test_escalation_creates_audit_entry`:升级 → 审计日志

---

### M2.7: LangGraph Workflow 编排器

**目标**:用 LangGraph 实现确定性状态机——"意图分类 → KB/Skill 路由 → Guardrail → 响应组装"。

**设计**:M2 阶段意图分类用关键词匹配(确定性);M3 升级为 Qwen 模型分类。

**LangGraph 状态机**:
```
                    ┌─────────────┐
                    │  START      │
                    │ (接收 query)│
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  classify   │  关键词匹配 → intent
                    │  _intent    │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──┐  ┌──────▼──┐  ┌──────▼──┐
       │ skill   │  │ kb      │  │ clarify │
       │ _route  │  │ _route  │  │         │
       └────┬────┘  └────┬────┘  └────┬────┘
            │            │            │
       ┌────▼────┐  ┌────▼────┐      │
       │guardrail│  │ format  │      │
       │ _check  │  │ _result │      │
       └────┬────┘  └────┬────┘      │
            │            │            │
       ┌────▼────┐       │            │
       │ format  │       │            │
       │ _result │       │            │
       └────┬────┘       │            │
            │            │            │
            └────────────┴────────────┘
                         │
                  ┌──────▼──────┐
                  │    END      │
                  │ (返回响应)  │
                  └─────────────┘
```

**改动**:
- 新增 `backend/orchestrator/` 包:
  - `intent.py`:意图分类(关键词映射)
    ```python
    INTENT_MAP = {
        "income_tax": ["所得税", "income tax", "federal tax", "报税", "收入税"],
        "feie": ["海外收入", "FEIE", "foreign earned", "330天", "海外工作"],
        "rsu": ["RSU", "restricted stock", "股票归属", "受限股票"],
        "crypto": ["加密", "crypto", "比特币", "bitcoin", "资本利得", "capital gain"],
        "nexus": ["nexus", "经济联结", "sales tax", "电商", "远程销售"],
        "knowledge": ["怎么", "什么是", "how", "what", "deadline", "截止", "扣除", "抵免"],
    }
    ```
  - `graph.py`:LangGraph StateGraph 定义(节点 + 边 + 条件路由)
  - `nodes.py`:各节点实现(classify / skill_route / kb_route / guardrail / format)
  - `response.py`:响应模板组装
- 新增路由:
  ```
  POST /api/assistant/query
  Body: { "query": "加州收入15万要交多少州税?", "profile_id": "..." }
  Response: {
    "intent": "income_tax",
    "answer": { ... structured ... },
    "sources": ["Rev. Proc. 2024-40", "CA FTB"],
    "tips": [...],
    "confidence": "engine_backed",
    "trace": { "nodes_visited": ["classify", "skill_route", "guardrail", "format"] }
  }
  ```

**测试**:
- `test_intent_routes_correctly`:各意图关键词 → 正确节点
- `test_skill_workflow_end_to_end`:税务问题 → Skill 调用 → 引擎结果
- `test_kb_workflow_end_to_end`:知识问题 → GraphRAG 检索 → 带源引用
- `test_clarify_on_ambiguous`:模糊问题 → 澄清提示(不编造)
- `test_guardrail_in_workflow`:workflow 中 guardrail 生效

---

### M2.8: KB 驱动税务提醒 + 截止日 ✅ (PR #59 merged 2026-06-08)

**目标**:根据用户档案,从知识图谱查询相关提醒和即将到来的截止日。

**改动**:
- 新增 `backend/knowledge/tips.py`:
  - `get_tips_for_profile(profile)`:
    - Neo4j 查询:从用户的州/收入类型 → 关联 TaxRule 节点 → 筛选 tip 类型
    - 排序:relevance(高收入→surtax、自雇→estimated tax、海外→FEIE)
  - `get_upcoming_deadlines(filing_status, state)`:
    - Neo4j 查询:Deadline 节点 → 按 applies_to 过滤 → 按 date 排序
- 新增路由:
  ```
  GET /api/tips?profile_id=...
  Response: {
    "tips": [
      { "title": "MA 4% Millionaire Surtax", "content": "...",
        "source": { "id": "MA DOR", "name": "..." }, "relevance": "high" }
    ],
    "deadlines": [
      { "date": "2026-04-15", "title": "Federal Filing Deadline", "applies_to": "all" }
    ]
  }
  ```

**测试**:
- `test_tips_self_employed`:自雇 → estimated tax 提醒
- `test_tips_foreign_income`:海外 → FEIE tip
- `test_tips_high_income_ma`:MA + >$1M → surtax 提醒
- `test_deadlines_sorted`:截止日按日期升序
- `test_tips_empty_profile`:空档案 → 通用提醒

---

### M2.9: 审计日志 🟡 (PR #61 open 2026-06-09)

**目标**:全链路追踪(计算/查询/档案访问),满足合规可追溯;PII 脱敏。

**改动**:
- 新增 `backend/audit/` 包:
  - `logger.py`:
    ```python
    async def log_action(
        request_id: UUID,
        user_id: UUID | None,
        action: str,
        input_data: dict,
        output_data: dict,
    ) -> None:
    ```
  - `sanitizer.py`:PII 脱敏(SSN → `***-**-1234`;收入金额保留;姓名 mask)
  - `middleware.py`:FastAPI middleware,自动记录 `/api/skills/*` + `/api/assistant/*`
- 新增路由(内部):
  ```
  GET /api/admin/audit?user_id=...&action=...&from=...&to=...
  ```
- 写入:异步批量(不阻塞响应)

**测试**:
- `test_audit_on_skill_call`:调 Skill → audit_log 有记录
- `test_audit_sanitized`:SSN 已脱敏
- `test_audit_request_id`:日志 request_id 与响应头一致

---

### M2.10: 集成测试 + M2 关闭

**目标**:端到端验证 M2 全链路,更新所有文档,正式关闭 M2。

**验证场景**:
1. 创建档案 → 保存 PostgreSQL → 读回一致
2. 查询 "加州所得税" → LangGraph → classify → skill_route → calculate_income_tax → guardrail → 引擎结果 + 源引用
3. 查询 "FEIE 是什么" → LangGraph → classify → kb_route → GraphRAG(Neo4j+Chroma) → 知识条目 + IRS 来源
4. 获取档案提醒 → Neo4j 图查询 → 个性化 tips + 截止日
5. 全部操作 → audit_log 完整链路 + PII 已脱敏
6. guardrail:伪造金额拦截;not_covered 保持诚实
7. 向后兼容:三库全关 → `/calc/*` 仍正常

**文档更新**:
- `project.md`:M2 状态 → 已完成
- `docs/roadmap_skills_status.md`:M2 → ✅ + Skills 状态更新
- `docs/feature_status.md`:新增 M2 各步交付记录
- `ARCHITECTURE.md` §2:更新为包含 Neo4j + Chroma + Skill + LangGraph

---

## 注意事项

1. **LLM 在 M2 中不上线**:意图分类 = 关键词匹配;响应 = 模板组装。自部署 Qwen + vLLM 在 M3 引入,届时 LangGraph 的 classify 节点和 format 节点升级为模型调用。
2. **数据不出境**:embedding 用本地 sentence-transformers;Neo4j/Chroma/PG 全部本地部署;不接任何第三方 API。
3. **向后兼容**:`/calc/*` 不依赖三库;任何存储不可用时 M1 功能照常。
4. **PII**:MVP profile data 存 JSONB 明文;M5 加列级加密。审计日志必须脱敏。
5. **幂等**:profile upsert(UNIQUE 约束)、knowledge ingestion(MERGE)、audit write(append-only)。
6. **可并行**:M2.1(三库) 与 M2.5(LangChain Skills) 无依赖可并行;M2.4(档案) 只依赖 PG 不依赖 Neo4j/Chroma,也可提前。
7. **Neo4j 学习成本**:团队首次引入图数据库;M2.1 需预留 Cypher 查询学习时间。
