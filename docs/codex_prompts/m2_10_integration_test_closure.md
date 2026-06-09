# Codex Prompt: M2.10 Integration Test + M2 Closure

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `docs/m2_step_plan.md` §M2.10
> Pre-read: all `tests/test_m2_*.py` files to understand existing test patterns

## Task

M2.1–M2.9 are all merged. This is the **final M2 step**: write an explicit acceptance test file that exercises the 7 M2 acceptance criteria end-to-end, update `ARCHITECTURE.md` to reflect the completed M2 architecture, and finalize all status documents to close M2.

**This is NOT about writing new unit tests** — 233 M2 tests already exist across 9 files. This step adds:
1. A formal `test_m2_10_integration.py` acceptance gate (7 tests, one per criterion)
2. ARCHITECTURE.md §2 rewrite to reflect M2-complete state
3. Status doc updates

## Core Constraints

1. **Backward compatibility**: All 357 existing tests must still pass unchanged
2. **No new dependencies**: Only use what's already in requirements.txt
3. **Test pattern**: Follow the existing `unittest` + `unittest.mock.patch` + `starlette.testclient.TestClient` pattern (see `test_m2_infrastructure.py` for the graceful degradation pattern, `test_m2_7_orchestrator.py` for orchestrator tests)
4. **No actual database required**: All tests must pass without PostgreSQL/Neo4j/Chroma running (mock as needed)

## Section 1: Integration Test File

### File: `tests/test_m2_10_integration.py`

Write 7 test methods, one per M2 acceptance criterion. Each test should exercise the **full path** through the system, not just individual components.

```python
"""M2.10 Integration acceptance tests — formal gate for M2 closure.

Each test maps to one M2 acceptance criterion from docs/m2_step_plan.md.
These exercise full request→response paths through the FastAPI app,
verifying that M2 components integrate correctly end-to-end.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from backend import config
from backend.main import create_app


class M2AcceptanceCriteria(unittest.TestCase):
    """7 acceptance criteria — all must pass to close M2."""

    # Criterion 1: Skill workflow produces correct tax amount + source
    # POST /api/assistant/query with "California income 150000"
    # → intent classified → skill invoked → engine result → sources attached
    def test_criterion_1_skill_workflow_returns_engine_result_with_source(self):
        ...

    # Criterion 2: Knowledge search returns results with IRS source
    # GET /api/knowledge/search?q=FEIE
    # → vector/graph search → results with source citations
    def test_criterion_2_knowledge_search_returns_results_with_source(self):
        ...

    # Criterion 3: Profile persistence (create → read back identical)
    # POST /api/profiles → GET /api/profiles/{id} → data matches
    def test_criterion_3_profile_create_and_read_back(self):
        ...

    # Criterion 4: KB-driven tips for self-employed user
    # GET /api/tips with self-employment context
    # → personalized tips including estimated tax deadline
    def test_criterion_4_self_employed_gets_estimated_tax_tip(self):
        ...

    # Criterion 5: Audit log written + PII sanitized
    # Invoke a skill → verify audit logger called with sanitized payload
    # SSN masked, income amounts preserved, names redacted
    def test_criterion_5_audit_log_written_with_pii_sanitized(self):
        ...

    # Criterion 6: Guardrail blocks fabricated amounts
    # Attempt to return an amount not from the engine → blocked
    def test_criterion_6_guardrail_blocks_fabricated_amount(self):
        ...

    # Criterion 7: All stores disabled → /calc/* still works
    # Disable PG + Neo4j + Chroma → /calc/federal-income returns correct result
    def test_criterion_7_calc_works_with_all_stores_disabled(self):
        ...
```

**Implementation notes for each test:**

1. **Criterion 1**: Use `TestClient` to `POST /api/assistant/query` with `{"query": "California income tax on income 150000", "filing_status": "single"}`. Mock the orchestrator's engine call to return a known Decimal result. Verify response has `intent`, `answer` with dollar amounts, `sources` list, and `confidence: "engine_backed"`.

2. **Criterion 2**: Use `TestClient` to `GET /api/knowledge/search?q=FEIE`. Mock vector_store and neo4j_client returns. Verify response `results` is non-empty, each result has `source` with `id` and `name`.

3. **Criterion 3**: Mock `_session_factory` to return an async session mock. `POST /api/profiles` with valid profile data → 200. Then `GET /api/profiles?user_id=...&tax_year=2026` → same data back. (Follow pattern from `test_m2_4_profiles.py`)

4. **Criterion 4**: Use `TestClient` to `GET /api/tips` with query params indicating self-employment income. Verify response `tips` list contains an item mentioning "estimated tax" or "quarterly". (Follow pattern from `test_m2_8_tips.py`)

5. **Criterion 5**: Import `sanitize_payload` directly. Feed it a dict containing `{"ssn": "123-45-6789", "income": 150000, "name": "John Doe"}`. Verify `ssn` → `***-**-6789`, `name` → `[redacted]`, `income` → `150000` (preserved). Also verify audit middleware integration by checking `log_action` is called when a skill endpoint is hit.

6. **Criterion 6**: Import guardrail validator. Create a result with a fabricated amount field that has no engine trace. Verify it returns `BLOCKED` or equivalent. (Follow pattern from `test_m2_6_guardrail.py`)

7. **Criterion 7**: Patch `config.ENABLE_POSTGRES = False`, `config.ENABLE_NEO4J = False`, `config.ENABLE_CHROMA = False`. Create `TestClient(create_app())`. Hit `GET /calc/federal-income?gross_income=100000&filing_status=single&tax_year=2025`. Verify 200 + `federal_tax` field present with correct Decimal value. (Follow pattern from `test_m2_infrastructure.py`)

## Section 2: ARCHITECTURE.md Update

Replace §2 to reflect M2-complete architecture. **Keep §0, §1, §5, §6 unchanged.** Update §2, §3, §4.

### New §2 (replace existing):

```markdown
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
  - `/api/states`（51 jurisdictions 动态列表）
  - `/api/health`（含三库连接状态）

### 2.2 计算引擎（M1，不变）
- 纯函数 + Decimal（模块化 `engine/` 包：money/brackets/payroll/qbi/feie/state/crypto/rsu/nexus/summary + 门面）。
- **无共享可变状态** → 天然水平扩展。
- 规则数据：版本化 JSON `data/tax_years/YYYY/`（2025+2026），`@lru_cache` + `MappingProxyType` 冻结缓存。

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
```

### New §3 (replace existing):

```markdown
## 3. 生产目标架构（M3–M5，**计划中**——前瞻审查 + 解锁矩阵全项）
- 前端 Next.js 14 + Tailwind；API FastAPI + WebSocket(流式 Copilot)。
- **M3 模型层**：自部署 Qwen 基座 + LoRA + vLLM(热加载 adapter)；Qwen-VL 做 W-2 OCR。**全部自部署,数据不出境。** 编排器意图分类从关键词匹配升级为模型分类。
- **M3 连接器**：Google/Apple/微信 OAuth；Shopify/Amazon(电商 Nexus 真连)。→ 需超时/重试风暴控制/熔断降级/限流;对外依赖故障不得拖垮核心计算链路。
- **M4 训练闭环**：Trace 回流 + LoRA 微调 + Eval Harness。
- **M5 合规上线**：PII 列级加密、HTTPS、生产部署、安全审计。
```

### New §4 (replace existing):

```markdown
## 4. 外部依赖
- **当前（M2）**：PostgreSQL（档案+审计，可选）、Neo4j（知识图谱，可选）、Chroma（向量库，可选，本地文件）、sentence-transformers（本地 embedding，可选）。**全部可选——关闭后核心计算不受影响。**
- **目标（M3+）**：自部署模型服务(vLLM)、OAuth 提供方、Shopify/Amazon API。每项落地时本文件更新 + 审查矩阵安全/性能/SRE 全项对其生效。
```

## Section 3: Status Document Updates

### File: `docs/feature_status.md`
- Line 3: Change to `最后更新：2026-06-09（M2.10 集成测试 + M2 关闭）`
- Add row in §D table: `| 集成测试 + M2 关闭 | ✅ | M2.10 PR #XX |`

### File: `docs/m2_step_plan.md`
- M2.10 row: Change `⬜` to `✅ PR #XX merged YYYY-MM-DD`

### File: `docs/roadmap_skills_status.md`
- Line 5: Update last-modified timestamp
- M2 row in §一 table: Change `🟡 **进行中**` to `✅ **已完成并关闭（2026-06-09）**`
- Add M2 closure summary similar to M1 closure summary

**Note**: Replace `#XX` with the actual PR number after creating the PR.

## Acceptance Gates

```powershell
# All 357+ existing tests still pass
python -m unittest discover -s tests

# Lint clean
python -m ruff check engine backend tests

# No whitespace issues
git diff --check
```

## Commit Format

```
test(m2.10): add integration acceptance tests and close M2

- Add tests/test_m2_10_integration.py with 7 acceptance criterion tests
- Update ARCHITECTURE.md §2-§4 to reflect M2-complete architecture
- Update status docs to mark M2 as closed

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
