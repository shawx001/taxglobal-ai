# TaxGlobal AI 目标驱动开发计划

创建日期：2026-06-02
原则：先美国、先规则引擎、先知识库可追溯；模型训练、自有大模型、全国际覆盖暂缓。

---

## 总目标

先做一个可以本地跑起来、可测试、可审计的美国税务 MVP：

- 用户选择身份并填写收入档案。
- 后端计算美国税务结果。
- 仪表盘生成优先级提醒和节税方案。
- 每个金额来自计算引擎。
- 每条提醒、建议、Copilot 回答都来自知识库。
- 所有规则可版本化、可更新、可回溯。

## 工程质量底线

- 代码必须模块化：前端只展示，API 只编排，引擎只计算，知识库只存规则和来源。
- 税务数字不能裸写在业务代码里；必须来自 `data/` 规则文件。
- 每个规则条目必须带 `source_url`、`citation`、`effective_date`、`tax_year`、`status`。
- 每个计算函数必须有测试，核心边界必须有黄金测试。
- 每个 API 返回必须包含 `rule_version`、`citations`、`assumptions`。
- 不确定的规则不能伪装成确定结论；标记为 `estimate`、`demo` 或 `unverified`。
- 不为了快而写临时大函数；如果确实需要临时实现，必须在本步交付里列为已知限制。
- Claude review 之前，每一步都要说明修改文件、验收命令、剩余风险。

## 大厂工程规范

- 每次修改都必须验证：代码变更跑自动化测试；配置/文档/目录变更也要跑对应的结构检查、文件校验或可读性检查。
- 每一步只解决一个明确目标，避免把无关重构混进功能提交。
- 先写或同步测试，再改实现；税务计算、知识库触发和 API 契约必须有回归测试。
- 所有外部输入必须校验：API request、规则 JSON、知识库条目、后续连接器数据都不能默认可信。
- 错误处理必须可诊断：返回统一错误结构，日志保留 request id / rule version / knowledge id，不吞异常。
- 数据和代码分离：税率、阈值、引用来源、提示触发条件不写死在业务逻辑里。
- 变更必须可回滚：旧规则保留版本，旧知识标记 `superseded`，数据库迁移必须可追踪。
- 默认最小权限：后续 OAuth、连接器、数据库账号、后台任务都只拿完成任务所需权限。
- 敏感数据最小化：只保存产品必要字段；税务输入、连接器 token、审计日志分级处理。
- 可观测性从早期预留：后端接口、计算引擎、知识库检索、提醒生成都要能记录耗时和错误率。
- API 契约稳定：前端依赖的 response schema 变更必须同步测试和文档。
- 命名清晰：文件、函数、字段名表达业务含义，不用模糊缩写。
- 小步提交：每个 step 完成后形成可 review 的变更集，说明目的、验收、风险。
- 不静默降级：知识库缺失、规则过期、API 不可用时要明确提示，不给用户假确定性。
- 不引入未经确认的大依赖：新增框架、数据库、队列、向量库前必须说明目的和替代方案。
- 保持原型可运行：迁移期间不要破坏根目录 `index.html` 的可打开状态，直到新前端完全接管。

## 税务规则数据来源原则

- 联邦所得税、标准扣除、FEIE 等：优先使用 IRS Revenue Procedure、Internal Revenue Bulletin、IRS instructions/publications。
- FICA、Social Security wage base：优先使用 SSA 官方 COLA fact sheet 和 IRS payroll tax guidance。
- 州税：优先使用各州税务局官方来源，例如 California FTB、New York Department of Taxation and Finance 等。
- Nexus 阈值：优先使用州税务局官方 sales tax/economic nexus 页面；平台代缴规则优先使用州官方和平台官方 tax policy 页面。
- 第三方博客、新闻、会计网站只能作为发现线索，不能作为最终规则来源。
- 新规则和旧规则冲突时，不直接删除旧规则；旧规则标记 `superseded`，新规则必须满足同 jurisdiction/topic/tax_year 且来源优先级更高或 effective_date 更新。

## 知识库真相源原则

- 生产逻辑只信数据库，不直接信外部网页。
- 外部网络只是“补充资料入口”，数据库才是“事实来源”。
- 计算引擎不直接联网查规则，只读取当前有效规则数据。
- Copilot 不直接联网找答案，只检索知识库并调用计算引擎。
- Dashboard 提醒不直接使用前端硬编码，必须由用户档案 + 知识库规则触发。
- 如果数据库没有覆盖某个问题，系统返回“知识库暂无覆盖”，并触发待更新任务。
- 如果数据库规则过时，系统从官方来源抓取/导入新文档，生成 diff，等待确认或按规则覆盖。
- 新文档覆盖旧文档时，必须匹配 `jurisdiction + topic + tax_year`，并且新文档 `status=effective`、来源优先级足够高。
- 旧文档不删除，只标记为 `superseded`，保留审计链路。
- 每个税务答案、提醒、建议都应可追溯到 `knowledge_id`、`rule_version`、`source_url`、`effective_date`。

暂缓：

- 自有模型训练 / LoRA / vLLM。
- 全国际深度税务覆盖。
- 真 E-file。
- 真 OCR/VLM。
- 真 Shopify/Amazon/Google/Apple/微信 OAuth。
- 企业税务完整模块。

---

# Step 0：建立工程基线

## 目的

把当前单文件原型变成一个可持续开发、可 review、可测试的项目。

## 要做什么

- 初始化 Git 仓库。
- 保留当前 `index.html` 原型。
- 建立基础目录：
  - `frontend/`
  - `backend/`
  - `engine/`
  - `data/`
  - `tests/`
  - `docs/`
- 写 README，说明当前项目状态和启动方式。

## 验收标准

- `git status` 正常。
- 项目目录结构清晰。
- 当前原型仍可打开。
- README 能解释项目是什么、怎么启动、下一步做什么。

## 预计更改文件

- 新增：`README.md`
- 新增：`frontend/index.html`
- 新增：`backend/`
- 新增：`engine/`
- 新增：`data/`
- 新增：`tests/`
- 新增：`docs/`
- 可能移动：根目录 `index.html` 到 `frontend/index.html`

## Review 重点

- 是否破坏了当前原型。
- 是否目录结构过度复杂。
- 是否 README 说清楚了 MVP 边界。

---

# Step 1：抽出美国税务规则数据

## 目的

把税率、扣除额、FICA、州税等从前端代码里拿出来，变成版本化数据。后续所有计算都从这些数据读取。

这一步不能信任原型里的硬编码数字。原型数据只作为“待核实线索”，正式规则必须来自官方来源，并把相应官方文档或页面快照保存下来，方便日后数据库入库、检索、diff 和规则覆盖。

## 要做什么

- 新建 2025 美国税务规则 JSON。
- 新建官方来源文档归档目录，保存本步使用的 IRS / SSA / 州税局来源文件或页面快照。
- 新建 source manifest，记录每份来源文档：
  - `source_id`
  - `title`
  - `source_url`
  - `source_type`
  - `publisher`
  - `retrieved_at`
  - `published_at`
  - `effective_date`
  - `tax_year`
  - `jurisdiction`
  - `topics`
  - `local_path`
  - `content_hash`
  - `status`
- 先覆盖原型中已有规则：
  - 联邦税率：single / mfj / hoh。
  - 标准扣除。
  - FICA：Social Security、Medicare、Additional Medicare。
  - 州税：CA、NY、IL、MA、CO、GA、TX、FL、WA、NV。
  - FEIE 上限。
- 每条规则带元数据：
  - `tax_year`
  - `jurisdiction`
  - `topic`
  - `value`
  - `source`
  - `citation`
  - `effective_date`
  - `status`
  - `notes`

## 验收标准

- 所有正式规则都有对应的归档 source document 或 source page snapshot。
- source manifest 可解析，且每个 `local_path` 指向真实文件。
- source document 有 hash，后续可检测文档是否变化。
- 数据文件是合法 JSON。
- 每条规则有来源字段。
- 2025 美国核心计算所需数据都能在 `data/` 里找到。
- 没有计算逻辑写在 JSON 里，只保存规则数据。
- 原型里的数字若无法被官方来源确认，必须标记为 `unverified`、`estimate` 或暂不进入正式规则。

## 预计更改文件

- 新增：`data/tax_years/2025/us_federal.json`
- 新增：`data/tax_years/2025/us_fica.json`
- 新增：`data/tax_years/2025/us_states.json`
- 新增：`data/tax_years/2025/us_feie.json`
- 新增：`data/sources/us/2025/source_manifest.json`
- 新增：`data/sources/us/2025/raw/*`
- 新增：`docs/step1_tax_rule_data.md`

## Review 重点

- 数据结构是否适合长期维护。
- citation 是否够明确。
- 官方来源文档是否已保存，是否可追溯。
- source manifest 是否包含 hash 和 retrieved_at。
- 是否混入了前端展示文案。
- 是否把“简化估算”标清楚。

---

# Step 2：实现 Python 税务计算引擎

## 目的

把浏览器里的计算逻辑下沉为纯函数，让税额结果可测试、可审计、可复用。

## 要做什么

- 在 `engine/` 里实现纯函数：
  - `bracket_tax`
  - `federal_income_tax`
  - `state_income_tax`
  - `fica_tax`
  - `income_tax_summary`
  - `rsu_tax_estimate`
  - `self_employment_tax`
  - `feie_estimate`
  - `crypto_gain_estimate`
  - `nexus_estimate`
- 每个函数输入普通 Python dict 或 typed model。
- 每个函数返回统一结构：
  - `input`
  - `result`
  - `breakdown`
  - `rule_version`
  - `citations`
  - `assumptions`

## 验收标准

- 引擎函数不依赖浏览器、DOM、localStorage。
- 引擎函数不依赖 FastAPI。
- 同样输入每次输出一致。
- 计算结果与当前 `index.html` 原型一致，除非明确修正并记录。

## 预计更改文件

- 新增：`engine/__init__.py`
- 新增：`engine/tax_engine.py`
- 新增：`engine/rules_loader.py`
- 新增：`engine/schemas.py`

## Review 重点

- 是否是纯函数。
- 是否把规则和计算分开。
- 是否有 rounding/边界处理问题。
- 是否有硬编码税率。

---

# Step 3：建立黄金测试集

## 目的

把当前原型已经验证过的场景固定下来，防止后续改动把税务结果改坏。

## 要做什么

- 创建黄金测试用例。
- 覆盖：
  - W-2 普通收入。
  - $200k Additional Medicare 边界。
  - 零州税州。
  - CA/NY 州税。
  - RSU。
  - 自雇税。
  - FEIE 达标/不达标。
  - Crypto HIFO/FIFO/LIFO。
  - Nexus 接近阈值/已触发。

## 验收标准

- `pytest` 全部通过。
- 每个测试说明场景目的。
- 每个测试输出包含 citation 和 assumptions。
- 测试失败时能清楚看到哪个税务模块变了。

## 预计更改文件

- 新增：`tests/test_income_tax.py`
- 新增：`tests/test_rsu.py`
- 新增：`tests/test_self_employment.py`
- 新增：`tests/test_feie.py`
- 新增：`tests/test_crypto.py`
- 新增：`tests/test_nexus.py`
- 新增：`tests/golden/*.json`

## Review 重点

- 测试是否只测 happy path。
- 边界条件是否够。
- 是否把错误结果也固化了。
- 测试命名是否清楚。

---

# Step 4：搭 FastAPI 最小后端

## 目的

让前端通过 API 使用计算引擎，为后续档案、知识库、提醒系统打基础。

## 要做什么

- 新建 FastAPI app。
- 暴露接口：
  - `GET /health`
  - `POST /calc/income`
  - `POST /calc/rsu`
  - `POST /calc/self-employment`
  - `POST /calc/feie`
  - `POST /calc/crypto`
  - `POST /calc/nexus`
- API 只调用 `engine/`，不自己写税务计算。
- 返回统一错误格式。

## 验收标准

- `GET /health` 返回正常。
- OpenAPI 文档可访问。
- 每个 `/calc/*` 接口能返回 result、breakdown、citations。
- 后端接口测试通过。

## 预计更改文件

- 新增：`backend/main.py`
- 新增：`backend/routes/calc.py`
- 新增：`backend/schemas.py`
- 新增：`backend/requirements.txt`
- 新增：`tests/test_api_calc.py`

## Review 重点

- API 是否薄。
- 是否有重复计算逻辑。
- 输入校验是否合理。
- 错误格式是否统一。

---

# Step 5：前端改为调用后端

## 目的

让产品从“前端自己算”变成“前端展示，后端计算”。

## 要做什么

- 保留现有 UI。
- 修改主要计算模块，调用 FastAPI：
  - 普通收入税。
  - RSU。
  - 自雇。
  - FEIE。
  - Crypto。
  - Nexus。
- 页面展示后端返回的 breakdown、citation、assumptions。
- 暂时不迁 Next.js。

## 验收标准

- 前端页面能正常打开。
- 至少普通收入税模块完全由后端返回。
- 后续模块逐个切换到后端。
- 关闭后端时，前端明确提示 API 不可用。
- 前端不再重复做核心税额计算。

## 预计更改文件

- 修改：`frontend/index.html`
- 可能新增：`frontend/app.js`
- 可能新增：`frontend/api.js`

## Review 重点

- 是否还残留重复计算。
- API 错误状态是否处理。
- 是否破坏现有交互。
- citation 是否显示清楚。

---

# Step 6：建立美国知识库 MVP

## 目的

让提醒、建议、Copilot 回答都来源于知识库，而不是写死在前端。

## 要做什么

- 建立知识库数据结构。
- 先覆盖美国核心主题：
  - 401k
  - HSA
  - RSU
  - Self-employment tax
  - Quarterly estimated tax
  - FEIE
  - FTC
  - FBAR
  - QBI
  - Crypto cost basis
  - Marketplace facilitator
  - Sales tax Nexus
- 每条知识包含：
  - `id`
  - `topic`
  - `jurisdiction`
  - `tax_year`
  - `summary`
  - `trigger_conditions`
  - `citations`
  - `source_url`
  - `effective_date`
  - `status`
  - `supersedes`

## 验收标准

- 仪表盘提醒能从知识库读。
- Copilot 能从知识库检索。
- 每条知识都有 citation。
- 没有来源的知识不能用于正式建议。

## 预计更改文件

- 新增：`data/kb/us/2025/*.json`
- 新增：`backend/routes/kb.py`
- 新增：`engine/knowledge.py`
- 新增：`tests/test_knowledge.py`

## Review 重点

- 知识结构是否能支持后续更新。
- trigger_conditions 是否可执行。
- citation 是否和内容对应。
- 是否把营销文案混进知识库。

---

# Step 7：知识库驱动提醒系统

## 目的

把 dashboard 的“你最需要知道的事”从前端写死，变成基于用户档案和知识库规则触发。

## 要做什么

- 定义用户 profile schema。
- 定义 alert 生成器。
- 根据 profile + knowledge trigger 生成提醒。
- 每条提醒返回：
  - `priority`
  - `title`
  - `body`
  - `why_triggered`
  - `recommended_action`
  - `citations`
  - `source_knowledge_id`

## 验收标准

- 自雇用户触发季度预缴提醒。
- 收入 > $200k 触发 Additional Medicare 提醒。
- 海外居住触发 FEIE/FBAR 相关提醒。
- 电商 Shopify 接近阈值触发 Nexus 提醒。
- 每条提醒能追溯到知识库条目。

## 预计更改文件

- 新增：`engine/alerts.py`
- 新增：`backend/routes/alerts.py`
- 新增：`tests/test_alerts.py`
- 修改：`frontend/index.html`

## Review 重点

- 提醒是否真的来自知识库。
- priority 规则是否合理。
- 是否出现无来源建议。
- 是否对不确定条件表达清楚。

---

# Step 8：Copilot MVP

## 目的

让 Copilot 成为“知识库检索 + 计算引擎调用”的解释层，而不是自由发挥的聊天机器人。

## 要做什么

- 建立 Copilot API。
- 用户问题先判断类型：
  - 金额类：调用计算引擎。
  - 法条/规则类：检索知识库。
  - 规划类：组合 profile + alerts + calculations + KB。
- 没有知识库来源时，回答“不确定，知识库暂无覆盖”。
- 国际问题暂时只给基础说明，不给确定税额结论。

## 验收标准

- Copilot 金额答案来自 `/calc/*`。
- Copilot 法条答案来自 KB。
- 回答附 citation。
- 不编造不存在的税率、规则、日期。
- 对暂未覆盖国家明确说明限制。

## 预计更改文件

- 新增：`backend/routes/copilot.py`
- 新增：`engine/copilot.py`
- 新增：`tests/test_copilot.py`
- 修改：`frontend/index.html`

## Review 重点

- Guardrail 是否清楚。
- 是否可能编数字。
- 无来源时是否拒绝确定回答。
- 是否泄漏内部实现细节。

---

# Step 9：持久化和真实用户档案

## 目的

让产品从一次性计算器变成可持续使用的税务助手。

## 要做什么

- 接 PostgreSQL。
- 建表：
  - users
  - profiles
  - calculations
  - alerts
  - knowledge_items
  - audit_logs
- 先用本地 mock login 或简单 email session。
- 不急着接真实 OAuth。

## 验收标准

- 用户档案可保存、读取、更新。
- 计算记录可保存。
- 每次税务结论保存 input、output、rule_version、citations。
- 审计日志可查询。

## 预计更改文件

- 新增：`backend/db.py`
- 新增：`backend/models.py`
- 新增：`backend/routes/profile.py`
- 新增：`backend/routes/history.py`
- 新增：`migrations/`
- 修改：`backend/requirements.txt`

## Review 重点

- 审计字段是否完整。
- 是否保存敏感数据过多。
- schema 是否支持多身份。
- 是否为后续 OAuth 留接口。

---

# Step 10：知识库定期更新系统

## 目的

让系统能定期从官方来源获取新规则，入库、比对、标记冲突，并保留历史版本。

## 要做什么

- 建立 source registry。
- 先只接官方/高可信来源：
  - IRS
  - Treasury
  - FinCEN
  - state tax agencies
  - official marketplace tax pages
- 定期抓取文件或页面。
- 抽取文本。
- 生成 candidate knowledge item。
- 和旧知识对比。
- 冲突时按规则处理：
  - `effective` 优先于 `proposed`
  - 官方来源优先于第三方
  - 同 jurisdiction/topic/tax_year 下，effective_date 更新者优先
  - 旧规则标记 `superseded`，不删除

## 验收标准

- 能手动运行一次更新任务。
- 能看到新增/更新/冲突报告。
- 冲突不会静默覆盖。
- 每次更新生成 diff。
- 被替代规则仍可审计。

## 预计更改文件

- 新增：`backend/jobs/update_knowledge.py`
- 新增：`engine/knowledge_update.py`
- 新增：`data/sources/us_sources.json`
- 新增：`tests/test_knowledge_update.py`

## Review 重点

- 是否错误地用新闻覆盖官方规则。
- 是否区分 proposed 和 effective。
- 是否保留历史版本。
- 是否有人工 review 入口。

---

# Step 11：美国 MVP 完整联调

## 目的

把计算、知识库、提醒、Copilot、档案串起来，形成一个可以演示的产品闭环。

## 要做什么

- 用户完成 onboarding。
- 保存档案。
- 后端计算税务结果。
- 知识库生成提醒。
- 仪表盘展示方案。
- Copilot 解释方案。
- 所有输出可追溯。

## 验收标准

- 科技员工场景可完整跑通。
- 自雇场景可完整跑通。
- 电商 Nexus 场景可完整跑通。
- 加密基础场景可完整跑通。
- 数字游民美国 FEIE 基础场景可完整跑通。
- 任何金额都有 engine 来源。
- 任何建议都有 KB 来源。

## 预计更改文件

- 修改：`frontend/index.html`
- 修改：`backend/*`
- 修改：`engine/*`
- 修改：`data/*`
- 修改：`tests/*`

## Review 重点

- 是否形成真实闭环。
- 是否还有前端硬编码建议。
- 是否有未引用来源的税务结论。
- 是否有明显误导性的国际税务表述。

---

## 每一步交付格式

以后每完成一步，都按这个格式交付给你和 Claude review：

```md
## 本步目标

说明为什么做这一步。

## 本步完成内容

列出具体做了什么。

## 修改文件

- `path/to/file`
- `path/to/file`

## 验收结果

- 运行了什么命令
- 结果如何
- 哪些测试通过
- 如果是文档/结构变更，说明执行了哪些非业务测试或校验

## Claude Review 重点

- 请重点看哪些风险
- 是否有税务逻辑问题
- 是否有架构问题

## 已知限制

本步暂时没做什么，为什么没做。
```
