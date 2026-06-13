# Phase C — Knowledge Retrieval Enhancement (设计文档)

> 作者：Claude（设计 + 自实现，2026-06-12，Shaw 授权"你写设计自己写coding"）
> 依据：`/AGENTS.md`（规则=数据、优雅降级、无单体、一步一 PR、防御性输入）+ `ARCHITECTURE.md` + `docs/m3_step_plan.md` 关闭标准里推迟的 Phase C。

## 背景：现状检索链路

`backend/knowledge/search.py:hybrid_search()` 当前：

```
query → embedder.embed_text → Chroma.query(top_k, cosine) → (可选 Neo4j 扩展)
      → 按向量 cosine score 排序 → 截断 top_k
```

排序信号**只有向量余弦相似度**。这有三个已知弱点：

1. **精度**：双编码器（bi-encoder）召回快但粗，top-1 不一定最相关——税务问题里"标准扣除额是多少"和"标准扣除额怎么用"向量很近，但答非所问的会排前面。
2. **诚实度**：没有相关性把关。哪怕 KB 里没有相关内容，也会返回"最不相关里相对最像"的 5 条，score 再低也照样给。M3.3 的 knowledge prompt 虽然让 LLM"召回为空/不相关时用通用知识、不报数字"，但它拿不到"这批召回其实都不相关"的信号。
3. **召回**：Neo4j 图扩展目前只做 1 跳（取直接关联的 jurisdiction/topic/source），没有"相关规则"的多跳。

## 目标

在不破坏现有降级契约（Chroma/Neo4j/embedder 全可选、`/calc/*` 不依赖）的前提下，分三步增强检索：

- **C.1 Cross-encoder 重排**：召回更宽候选池 → 交叉编码器精排 → 取 top_k。**精度**。
- **C.2 CRAG 纠错层**：用重排分数给召回质量打分；低于阈值 → 标记 `low_confidence` + 丢弃明显不相关 chunk，让响应层据此诚实回答。**诚实度**。
- **C.3 Neo4j 多跳扩展**：从命中规则沿"同主题/同管辖区"再跳一层取相关规则。**召回**（依赖 Neo4j 在线）。

每步独立 PR、各自多 agent 评审 + CI 绿 + merge。全程遵守：**重排/纠错只改变知识检索结果的排序与置信标记，绝不触碰规则引擎的税务数字**（LLM=耳朵+嘴，引擎=大脑的边界不变）。

---

## C.1 Cross-encoder 重排

### 设计

- 新模块 `backend/knowledge/reranker.py`，镜像 `embedder.py` 的生命周期：`init_reranker()` / `close_reranker()` / `is_reranker_available()` / `rerank(query, passages) → list[float]`。懒加载、`local_files_only`、加载失败优雅降级（与 embedder 完全一致）。
- 模型：`BAAI/bge-reranker-base`（中英双语 cross-encoder，与现有 `BAAI/bge-small-zh-v1.5` 嵌入器同系，覆盖 zh 查询 + en KB 内容）。可经 `TAXGLOBAL_RERANK_MODEL` 覆写。
- `vector_search` 召回**更宽的候选池**：池大小 = `min(MAX_RERANK_POOL, max(top_k, RERANK_POOL))`，其中 `RERANK_POOL` 默认 20、`MAX_RERANK_POOL=80`（与最终 `top_k` 上限 `MAX_TOP_K=20` 解耦，使 `RERANK_POOL>20` 真正生效而非被静默裁到 20，同时把 cross-encoder 计算量封顶）。`hybrid_search` 在向量召回后、图扩展前，对候选 `(query, content)` 跑 cross-encoder，按重排分数排序，再截断到 `top_k`。
- **降级**：`ENABLE_RERANK=true`（默认开，但模型不可用即静默回退到向量序——CI 无模型时自动走这条，测试不破）。`ENABLE_RERANK=false` 时完全走原向量路径，零行为变化。
- 重排分数写进结果 `rerank_score` 字段，`query_metadata.reranked: bool` 标记是否实际重排过。原 `score`（向量 cosine）保留，供对照/审计。

### 配置

```
TAXGLOBAL_ENABLE_RERANK=true                 # 默认 True；模型缺失自动降级
TAXGLOBAL_RERANK_MODEL=BAAI/bge-reranker-base
TAXGLOBAL_RERANK_POOL=20                      # 召回候选池大小（重排前）
```

### 测试

- `reranker.py` 单元：模型不可用 → `rerank` 抛 RuntimeError / `is_reranker_available()` False。
- `hybrid_search` 重排路径（注入 fake reranker，验证顺序按重排分重排、截断正确、`reranked=True`）。
- 降级：reranker 不可用 → 向量序不变、`reranked=False`、结果与 C.1 前逐字节一致。
- `ENABLE_RERANK=false` → 零调用、原行为。
- 防御：空 passages、reranker 抛异常 → 回退向量序不崩。

---

## C.2 CRAG 纠错层（Corrective RAG）

### 设计

- 重排分数（cross-encoder logit/sigmoid）天然就是相关性信号，CRAG 复用它，无需额外模型。
- 在 `hybrid_search` 出口给整批召回判级：
  - 最高重排分 ≥ `RELEVANT` 阈值 → `confidence="high"`，正常返回。
  - 介于 `RELEVANT` 和 `AMBIGUOUS` 之间 → `confidence="medium"`，返回但标记。
  - 低于 `AMBIGUOUS` → `confidence="low"`，**丢弃明显不相关 chunk**（低于 `AMBIGUOUS` 的全部剔除），`results` 可能为空。
- `query_metadata` 增加 `confidence` 字段。`backend/orchestrator/nodes.py:kb_route_node` 把它透传到 state；`response.py` 的 knowledge prompt 据此：`low` → 走"KB 无相关内容，用通用概念解释、不报数字"分支（这条分支已存在，现在有了真信号驱动它）。
- 阈值来自 config（可调），默认基于 bge-reranker sigmoid 分数经验值（先保守，接真实查询后再校准）。
- **降级**：未重排（reranker 不可用）时 CRAG 用向量 cosine 分数退化判级，阈值另设；或标 `confidence="unknown"` 不干预。`ENABLE_RERANK=false` 时 CRAG 不激活。

### 测试

- 高分召回 → high，全保留。
- 中分 → medium，保留 + 标记。
- 低分 → low，剔除不相关、results 可能空、confidence=low。
- kb_route_node 透传 confidence；response.py low 分支被触发（mock LLM）。

---

## C.3 Neo4j 多跳扩展（依赖 Neo4j 在线）

### 设计

- 扩展 `graph_search`：除现有 1 跳（直接 jurisdiction/topic/source），增加 2 跳"相关规则"——`(命中规则)-[:ABOUT]->(t:Topic)<-[:ABOUT]-(related:TaxRule)`，取同主题的其它规则作为 `related_rules`，按出现频次/重叠度排序取前 N。
- 结果 `related_rules` 字段供前端"相关条目"展示与 LLM 补充上下文（仍只是知识，不参与计算）。
- 多跳查询加 `LIMIT` 防爆炸；批量单查询（现有模式）；Neo4j 不在线 → 跳过（现有降级）。
- **本环境 Neo4j 未运行**，C.3 先**设计 + 写代码 + 单元测试（mock run_query）**，真实多跳验证待 Neo4j 起服务（与 W-2 vision 同理：代码就绪、外部依赖待开）。

### 测试

- mock `run_query` 返回多跳行 → `related_rules` 正确解析、去重、截断。
- Neo4j 不可用 → 空扩展、降级。

---

## 不做（本阶段 YAGNI）

- 不引入查询改写/HyDE（M3 已有对话改写层，知识查询暂不需要）。
- 不做向量库重灌或 chunk 策略调整（2065 条已入库，质量问题用重排+CRAG 解决，不动数据层）。
- 不做跨语言翻译召回（bge 系本身跨 zh/en）。

## 风险与边界

- 重排模型 ~1.1GB，启动加载增加内存/启动时间——可经 `ENABLE_RERANK=false` 关闭；CI/无模型环境自动降级。
- 阈值需用真实查询校准；首版取保守经验值并在 `query_metadata` 暴露分数供观测。
- 绝不影响 `/calc/*` 与税务数字：重排/CRAG 只作用于 `knowledge` 意图的检索结果排序与置信标记。
