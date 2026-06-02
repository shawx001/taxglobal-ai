# Step 4 设计文档 — FastAPI 最小后端（把引擎接成服务）

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：`engineering_process.md`、`coding_standards.md`、`code_review_checklist.md`、引擎层 9 函数
分支：`feature/step4-fastapi`
角色：Claude 出设计 + 评审；Codex 实现。

> 目的：把已就绪的引擎函数暴露成 HTTP API，让 Step 5 前端能调用。**API 只编排，不写任何税务计算**——所有税额仍来自 `engine/`。本步不做前端、不做账号、不做持久化。
> 首次启用规范：Pydantic 强校验、统一结构化错误、请求级 TraceID + 结构化日志、依赖锁定（`requirements.txt`，CI 的 `pip-audit` 转为阻塞）。

---

## 1. 依赖与运行（已在原始计划内，非临时引入）
- 新增依赖：`fastapi`、`uvicorn[standard]`、`pydantic`（v2）。`backend/requirements.txt` 锁定版本。
- 备选评估：Flask（需另配校验/文档）；选 FastAPI 因自带 Pydantic 校验 + 自动 OpenAPI 文档，契合"输入必校验 + 契约稳定"。
- 运行：`uvicorn backend.main:app`；OpenAPI 文档 `/docs` 自动可访问。

## 2. 接口清单（与引擎 1:1，最薄编排）

| 方法 | 路径 | 调用引擎 | 入参(Pydantic) |
|---|---|---|---|
| GET | `/health` | — | — |
| POST | `/calc/federal-income` | `federal_income_tax` | gross_income, filing_status, deduction? |
| POST | `/calc/fica` | `fica_tax` | wages, filing_status |
| POST | `/calc/state-income` | `state_income_tax` | state_code, taxable_income |
| POST | `/calc/self-employment` | `self_employment_tax` | net_self_employment_profit, filing_status |
| POST | `/calc/feie` | `feie_estimate` | foreign_earned_income, days_abroad |
| POST | `/calc/crypto` | `crypto_gain_estimate` | lots[], disposals[], method, filing_status, other_taxable_income, modified_agi? |
| POST | `/calc/rsu` | `rsu_tax_estimate` | shares_vested, fmv_per_share, vest_date, filing_status, other_taxable_income, sale_scenario? |
| POST | `/calc/nexus` | `nexus_estimate` | state_code, sales_amount, transaction_count? |

- 全部 `tax_year` 默认 2025、可选传入。
- **1:1 而非合并**：保持 API 薄、可独立测；"多收入合并总览"(`income_tax_summary` + `/calc/summary`)等引擎函数建好后再加（见决策 D4-2）。
- 响应体：**直接透传引擎返回的 8 键结构**（status/input/result/breakdown/rule_version/citations/assumptions/reason），不在 API 层重塑，保证前端看到的就是引擎的可追溯输出。

## 3. 状态 → HTTP 映射（决策 D4-1）

| 引擎/情形 | HTTP | 说明 |
|---|---|---|
| `status: ok` | 200 | 正常结果 |
| `status: not_covered` | **200** | 这是**合法业务答案**("没法规无法计算+原因")，不是错误；前端据 body 显示诚实提示 |
| `status: invalid_input`（引擎域校验，如超卖） | **422** | 用户数据问题 |
| Pydantic 校验失败（类型/缺字段/越界） | 422 | FastAPI 自动 |
| 未预期异常 | 500 | 记日志(含 request_id)，返回统一错误体，**不吞、不泄漏内部栈** |

> not_covered 用 200 是刻意的：它和"加州税表正在录入"这种诚实提示一脉相承，不应被前端当成报错弹窗。

## 4. 统一错误体（决策 D4-3）
```json
{ "error": { "code": "invalid_input | validation_error | internal_error",
             "message": "人类可读说明",
             "request_id": "uuid",
             "details": [] } }
```
- 业务/校验错误 message 友好可展示；500 的 message 不含内部实现细节(coding_standards：不泄漏)。

## 5. 可观测性（首次启用，最小实现，决策 D4-4）
- **请求级 TraceID**：中间件为每个请求生成 `request_id`(uuid)，写入响应头 `X-Request-ID` + 所有日志。
- **结构化日志**：每请求一行：method、path、status_code、duration_ms、request_id；错误额外记 reason。输出到 stdout(后续可接 ELK/SLS)。
- 不吞异常：未捕获异常统一处理器 → 记 error 日志 + 500 错误体。

## 6. 输入校验（防御性，coding_standards）
- Pydantic 负责类型/必填/范围(如 quantity>0、days_abroad 合理区间、filing_status 枚举含 alias)。
- 引擎自身的域校验(超卖、未知州等)**保留**作为第二道防线(defense-in-depth)；不因为有了 Pydantic 就删引擎校验。

## 7. 与产品需求的衔接（REQ-001 / REQ-002，见 product_backlog）
- **REQ-001 收入分美国/海外**：在 API 层体现为——美国境内收入走 `/calc/federal-income`+`/calc/fica`+`/calc/state-income`；海外收入走 `/calc/feie`。本步把"分桶后各打哪个接口"的基础铺好；真正的合并总览(`income_tax_summary`)与档案分桶 schema 留到合并函数/Step 9。
- **REQ-002 档案同步**：本步只提供"无状态计算接口"；"档案点开即带入、改了重算"是 Step 5 前端 + 后续持久化的事。Step 4 确保接口契约稳定，Step 5 才能稳定对接。

## 8. 测试（`tests/test_api_calc.py`，用 FastAPI TestClient）
- `/health` 返回 200 + {status:"ok"}。
- 每个 `/calc/*`：正常入参 → 200 且 body 含 result/rule_version/citations。
- `not_covered`：`/calc/state-income` 传 CA → 200 且 body status=not_covered + reason。
- `invalid_input`：`/calc/crypto` 超卖 → 422 + 统一错误体。
- 校验失败：缺字段/类型错 → 422。
- 响应头含 `X-Request-ID`。
- OpenAPI：`/openapi.json` 可取且含全部路由。
- **不重复测税额数值**(那是引擎黄金测试的职责)；API 测试只验"编排、契约、状态映射、错误格式"。

## 9. CI 变更
- 安装 `backend/requirements.txt`；新增 API 测试进 `unittest discover`(或 pytest)。
- **`pip-audit` 转为阻塞**：现在有真实第三方依赖了，扫 CVE。
- ruff 覆盖 `backend/`。

## 10. 设计决策汇总
- **D4-1** 状态→HTTP：ok/​not_covered=200，invalid_input/校验=422，异常=500。
- **D4-2** 接口与引擎 1:1；合并总览延后到 `income_tax_summary`。
- **D4-3** 统一错误体 `{error:{code,message,request_id,details}}`。
- **D4-4** 每请求 TraceID + 结构化日志(stdout)。
- **D4-5** API 零税务逻辑，只调引擎；引擎域校验保留为第二道防线。

## 11. 范围外（写进已知限制）
账号/鉴权、持久化、限流、CORS 生产策略、多收入合并总览、真实部署编排——分别属 Step 5/9 及之后。

## 12. 交付物与分工
- **Codex**：`backend/main.py`(app+中间件+异常处理)、`backend/routes/calc.py`、`backend/schemas.py`(Pydantic)、`backend/requirements.txt`、`tests/test_api_calc.py`；`backend/` 纯编排、无税率/无计算；分支 `feature/step4-fastapi`，PR 到 main，CI(含阻塞 pip-audit)绿。把本设计文档一并提交。
- **Claude**：本设计；实现后评审——确认 API 不含税务逻辑、状态映射正确、错误体统一、TraceID/日志到位、not_covered 用 200、invalid 用 422。
- **Shaw**：合并 PR。

## 13. 退出门槛
- [ ] `/health` 200；8 个 `/calc/*` 各自 200 透传引擎结果。
- [ ] not_covered→200(body)、invalid_input→422、校验失败→422、异常→500 + request_id。
- [ ] OpenAPI `/docs` 与 `/openapi.json` 可访问。
- [ ] API 层无任何税率/计算逻辑(grep 确认)；引擎仍是唯一计算来源。
- [ ] ruff + unittest + 数据校验 + **pip-audit(阻塞)** CI 全绿；两份 index.html hash 不变。
- [ ] Claude review 通过([Blocker]/[Major]/[Minor])。
