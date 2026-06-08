# Codex Prompt: M2.2 知识图谱建模 + 数据入库

> 先读：`/AGENTS.md`（铁律）→ `/ARCHITECTURE.md` → `docs/m2_step_plan.md` M2.2 节

## 目的

M2.1 搭好了三库基础设施（PostgreSQL / Neo4j / Chroma / local embedding），但库是空的。
M2.2 的目标是：**设计知识图谱 schema，扩充知识数据到 ~70 条，写入库脚本把数据同时灌进 Neo4j（实体关系）和 Chroma（语义向量）。**

完成后，M2.3（GraphRAG 检索 API）才能有数据可查。

## 核心约束

1. **数据即真相**：所有知识条目存在 versioned JSON 文件中（`data/knowledge/`），入库脚本只读 JSON → 写库，**不硬编码任何税法数据**
2. **每条必须有 source_id**：没有来源出处的知识条目不允许入库，入库脚本要校验
3. **幂等入库**：Neo4j 用 `MERGE`（不是 `CREATE`），Chroma 用 `upsert`。重复执行不创建重复数据
4. **向后兼容**：不改任何现有 `/calc/*` 或 `/api/*` 路由逻辑
5. **数据不出境**：embedding 用 M2.1 已有的 `backend/knowledge/embedder.py`（local_files_only=True），不调外部 API
6. **graceful degradation**：Neo4j/Chroma 不可用时入库脚本报 warning 但不 crash

---

## 1. 扩充知识数据

### 文件：`data/knowledge/us/2026/us_core_knowledge.json`

新建（2026 税年版本）。Schema 与现有 `data/knowledge/us/2025/us_core_knowledge.json` 保持一致。

**现有 2025 版只有 5 条。扩充到 ~70 条，覆盖以下类别：**

| 类别 | 条目数 | 代表性条目 |
|------|--------|------------|
| 联邦核心 | ~25 | 标准扣除、SALT $10k cap、慈善扣除(AGI 60%)、学生贷款利息($2,500)、IRA、Roth conversion、QBI §199A(20%)、AMT、EITC、Child Tax Credit($2,000)、Dependent Care Credit、Education Credits(AOTC/LLC)、NIIT(3.8%)、Capital Gains brackets(0/15/20%)、Kiddie Tax、Medicare surtax |
| 截止日 | ~8 | 4/15 filing、6/15 estimated(海外)、9/15 estimated、1/15 estimated、10/15 extension、W-2 deadline(1/31)、1099 deadline、4868 extension |
| FEIE/FTC | ~5 | Physical Presence(330天)、Bona Fide Residence、Housing Exclusion、FTC basics、Form 2555 |
| 州级 gotchas | ~15 | MA 4% millionaire surtax、NJ gross-income 门槛、WA capital gains 7% excise、OR no sales tax、CA top rate 13.3%、NY/NYC city tax、TX/FL/NV/WA/WY no income tax、IL flat 4.95%、PA flat 3.07%、CT capital gains as ordinary、HI top rate 11% |
| 数字游民/多州 | ~5 | State residency rules、domicile vs statutory resident、nexus triggers、convenience-of-employer(NY/CT/PA/NJ)、safe harbor days |
| 加密货币 | ~5 | Cost basis methods(FIFO/Specific ID)、holding period(long/short)、1099-DA(new 2026)、staking as ordinary income、NFT collectibles rate(28%) |
| 自雇/RSU | ~5 | SE tax(15.3%/2.9%)、QBI safe harbor($400 threshold)、RSU double-tax risk、ISO/NSO basics、Section 83(b) election |

每条结构遵循现有 schema：
```json
{
  "knowledge_id": "us_2026_<topic>_<specific>",
  "topic": "<topic>",
  "jurisdiction": "US" | "<state_code>",
  "effective_date": "2026-01-01",
  "summary": "<1-3 sentences, factual, precise numbers>",
  "trigger_conditions": { ... },
  "source_ids": ["<source_id>"],
  "status": "effective"
}
```

**source_ids 规则**：
- 联邦条目引用 IRS 来源：`irs_rp_2025_32`（Rev.Proc. 2025-32，2026 inflation adjustments）、`irs_pub_17`、`irs_pub_501`、`irs_pub_54` 等
- 州条目引用州税务机关：`ca_ftb_rate_schedule`、`ny_dtf_rate_schedule`、`ma_dor_millionaire_surtax` 等
- 已有 source manifest 在 `data/sources/us/2026/source_manifest.json`，新增的 source_id 需同步更新此文件

### 文件：`data/sources/us/2026/source_manifest.json`

在现有 `sources` 数组中追加新引用的来源条目。每条格式：
```json
{
  "source_id": "irs_pub_17",
  "title": "IRS Publication 17: Your Federal Income Tax",
  "source_url": "https://www.irs.gov/publications/p17",
  "source_type": "html",
  "publisher": "Internal Revenue Service",
  "tax_year": 2026,
  "jurisdiction": "US",
  "topics": ["federal_income_tax", "standard_deduction", "credits"],
  "status": "reference"
}
```

---

## 2. 入库脚本

### 文件：`backend/knowledge/ingestion.py`（新建）

```python
"""Knowledge ingestion: JSON → Neo4j (graph) + Chroma (vectors)."""

# 公共接口:
# - ingest_to_neo4j(items, sources) → int  (返回创建/更新的节点数)
# - ingest_to_chroma(items) → int  (返回 upsert 的文档数)
# - ingest_all(knowledge_path, source_manifest_path) → dict  (返回统计)
# - validate_items(items) → list[str]  (返回错误列表，空=合法)
```

#### 2a. validate_items(items)

- 检查每条 item 必须有 `knowledge_id`, `topic`, `jurisdiction`, `summary`, `source_ids`
- `source_ids` 不能为空列表
- `knowledge_id` 不能重复
- 返回错误消息列表，空列表 = 校验通过

#### 2b. ingest_to_neo4j(items, sources)

- 依赖 `backend/knowledge/neo4j_client.py` 的 `run_query()` 和 `is_neo4j_available()`
- 如果 Neo4j 不可用：log warning + return 0（不 raise）
- 用 **MERGE**（非 CREATE）保证幂等：
  ```cypher
  MERGE (r:TaxRule {id: $id})
  SET r.title = $title, r.content = $content, r.tax_year = $tax_year, r.rule_type = $rule_type
  ```
- 创建 Jurisdiction 节点 + APPLIES_TO 关系：
  ```cypher
  MERGE (j:Jurisdiction {code: $jurisdiction})
  SET j.name = $name, j.type = $type
  MERGE (r)-[:APPLIES_TO]->(j)
  ```
  - jurisdiction 类型推断：`"US"` → type=`"federal"`，2 字母大写 → type=`"state"`
- 创建 Topic 节点 + ABOUT 关系
- 创建 Source 节点 + CITED_FROM 关系（Source 信息从 source_manifest 读取）
- 返回处理的节点数

#### 2c. ingest_to_chroma(items)

- 依赖 `backend/knowledge/vector_store.py` 的 `get_collection()` 和 `is_chroma_available()`
- 依赖 `backend/knowledge/embedder.py` 的 `embed_batch()`
- 如果 Chroma 或 embedder 不可用：log warning + return 0（不 raise）
- 对每条 item：
  - document text = `f"{item['topic']}: {item['summary']}"`
  - id = item["knowledge_id"]
  - metadata = `{"jurisdiction": ..., "topic": ..., "tax_year": ..., "source_ids": json.dumps(source_ids)}`
- 用 `collection.upsert()` 批量写入（分批，每批 max 100 条）
- 返回 upsert 的文档数

#### 2d. ingest_all(knowledge_dir, source_manifest_path)

- 读取 `knowledge_dir` 下所有 `*.json` 文件，合并所有 items
- 读取 source_manifest_path 获取来源信息
- 调用 validate_items() — 有错误则 raise ValueError
- 分别调用 ingest_to_neo4j() 和 ingest_to_chroma()
- 返回 `{"neo4j_count": ..., "chroma_count": ..., "total_items": ..., "errors": [...]}`

#### 2e. CLI 入口

```python
if __name__ == "__main__":
    # python -m backend.knowledge.ingestion [--knowledge-dir PATH] [--source-manifest PATH] [--tax-year 2026]
    import argparse
    # 默认 knowledge_dir = data/knowledge/us/2026/
    # 默认 source_manifest = data/sources/us/2026/source_manifest.json
```

---

## 3. 测试

### 文件：`tests/test_m2_2_ingestion.py`（新建）

所有测试 **不依赖真实 Neo4j/Chroma/embedding 模型**——用 mock/patch。

```python
class TestValidation(unittest.TestCase):
    """验证 validate_items() 数据校验逻辑。"""

    def test_valid_items_pass(self):
        """合法数据 → 空错误列表"""

    def test_missing_source_ids_fails(self):
        """source_ids 空列表 → 返回错误"""

    def test_missing_knowledge_id_fails(self):
        """无 knowledge_id → 返回错误"""

    def test_duplicate_knowledge_id_fails(self):
        """重复 knowledge_id → 返回错误"""

    def test_missing_summary_fails(self):
        """无 summary → 返回错误"""


class TestIngestionNeo4j(unittest.TestCase):
    """验证 Neo4j 入库逻辑（mock run_query）。"""

    def test_ingest_creates_nodes(self):
        """入库 N 条 → run_query 被调用正确次数"""

    def test_ingest_uses_merge_not_create(self):
        """Cypher 语句包含 MERGE，不包含 CREATE"""

    def test_ingest_creates_relationships(self):
        """TaxRule→Jurisdiction、TaxRule→Topic、TaxRule→Source 关系都创建"""

    def test_neo4j_unavailable_returns_zero(self):
        """Neo4j 不可用 → return 0，不 raise"""

    def test_jurisdiction_type_inference(self):
        """US → federal, CA → state"""


class TestIngestionChroma(unittest.TestCase):
    """验证 Chroma 入库逻辑（mock collection + embedder）。"""

    def test_ingest_upserts_documents(self):
        """入库 N 条 → collection.upsert 被调用"""

    def test_chroma_unavailable_returns_zero(self):
        """Chroma 不可用 → return 0，不 raise"""

    def test_metadata_includes_required_fields(self):
        """upsert 的 metadata 包含 jurisdiction, topic, tax_year"""

    def test_document_text_format(self):
        """document = '{topic}: {summary}'"""


class TestIngestAll(unittest.TestCase):
    """验证 ingest_all() 端到端编排。"""

    def test_ingest_all_returns_stats(self):
        """返回 dict 包含 neo4j_count, chroma_count, total_items"""

    def test_ingest_all_validation_error(self):
        """数据校验失败 → raise ValueError"""

    def test_idempotent_double_run(self):
        """执行两次，第二次不增加新数据"""


class TestKnowledgeDataIntegrity(unittest.TestCase):
    """验证知识 JSON 数据本身的质量。"""

    def test_all_items_have_source_ids(self):
        """读取真实 JSON，每条 source_ids 非空"""

    def test_no_duplicate_knowledge_ids(self):
        """所有 knowledge_id 全局唯一"""

    def test_minimum_item_count(self):
        """至少 60 条（目标 ~70）"""

    def test_jurisdiction_coverage(self):
        """至少覆盖 federal + 5 个州"""

    def test_topic_coverage(self):
        """至少覆盖 8 个不同 topic"""

    def test_source_manifest_covers_all_source_ids(self):
        """知识条目引用的所有 source_id 都在 source_manifest 中有记录"""
```

---

## 4. 不做什么

- **不改** `backend/main.py`（入库是离线批处理，不是 app startup）
- **不改** 任何 `/calc/*` 路由
- **不加** 新的 API endpoint（M2.3 做）
- **不改** `backend/knowledge/neo4j_client.py` / `vector_store.py` / `embedder.py` 的接口
- **不做** 增量更新/CDC — MVP 全量覆盖即可

---

## 5. 文件清单

| 操作 | 文件 |
|------|------|
| 新建 | `data/knowledge/us/2026/us_core_knowledge.json`（~70 条知识条目） |
| 修改 | `data/sources/us/2026/source_manifest.json`（追加新 source 条目） |
| 新建 | `backend/knowledge/ingestion.py`（入库脚本 + CLI） |
| 新建 | `tests/test_m2_2_ingestion.py`（入库 + 数据质量测试） |

---

## 6. 验收门禁

1. `python -m unittest discover -s tests` — 全绿（包括现有 118 + 新增）
2. `ruff check engine backend tests` — 0 errors
3. `python -m backend.knowledge.ingestion --help` — CLI 正常显示帮助
4. `data/knowledge/us/2026/us_core_knowledge.json` — ≥ 60 条，每条有 source_ids
5. 所有 source_ids 在 `source_manifest.json` 中有对应记录
6. 现有 M1 API (`/calc/*`, `/api/states`, `/health`) 不受影响

---

## 7. 分支

```
git checkout -b feat/m2-2-knowledge-graph-ingestion
```

一个 PR，squash merge 到 main。
