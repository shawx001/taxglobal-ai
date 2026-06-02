# TaxGlobal AI MVP 执行打勾清单

创建日期：2026-06-02
目标：先把现在的可点击原型变成一个能本地跑、能测试、能逐步接后端的 MVP。

---

## 0. 当前文件夹快照

- [x] `index.html`：单文件前端原型，包含 UI、状态、税务计算、模拟登录、模拟连接器、Copilot 本地 KB。
- [x] `TaxGlobal_AI_PRD_v1.1.md`：产品需求文档。
- [x] `TaxGlobal_AI_项目计划书_v3.1.md`：项目计划书。
- [x] 当前目录初始化 Git 仓库。
- [x] 建立工程目录：`backend/`、`engine/`、`frontend/`、`data/`、`tests/`。

---

## 1. 我看到的主要问题

- [ ] 范围过大：10 周路线很完整，但第一轮不要同时做 Next.js、FastAPI、OAuth、GraphRAG、自有模型、连接器、OCR。先把“计算引擎服务化”跑通。
- [ ] 计算逻辑范围要重新圈定：不仅是 `index.html:1108-1210`，还包括 `calcRSU`、`calcSE`、`calcFEIE`、`calcTreaty`、`calcCrypto`、`calcBiz` 等后续函数。
- [ ] 税率和法条需要版本化：前端里现在有不少简化模型，生产化前必须标注“真实规则 / 简化估算 / 演示规则”。
- [ ] Copilot 不要急着做模型训练：MVP 先做“检索 + 引擎工具调用 + 引用来源”，等 trace 和评测集稳定后再 LoRA。
- [ ] OAuth 和连接器先做假后端也可以：第一版可先用真实后端 session + mock provider，等计算引擎稳定后再接 Google/Apple/微信/Shopify/Amazon。
- [ ] 文档中“自有模型不接第三方 LLM”和“真实 LLM Claude”表述需要统一，避免后面工程目标冲突。

---

## 2. M0：今天先跑起来

- [x] `git init`。
- [x] 初始提交当前原型和文档。
- [x] 新建 `frontend/`，先把 `index.html` 放进去跑静态服务，不急着迁 Next.js。
- [ ] 新建 `engine/`，放 Python 纯函数税务引擎。
- [ ] 新建 `backend/`，用 FastAPI 暴露最小 API。
- [x] 新建 `data/tax_years/2025/`，放联邦、州税、FICA、FEIE 等 JSON 税率表。
- [x] 新建 `data/sources/us/2025/raw/`，归档本步使用的官方来源文件。
- [ ] 新建 `tests/golden/`，保存黄金测试输入和期望输出。
- [ ] 本地启动：
  - [ ] 前端静态服务。
  - [ ] 后端 FastAPI 服务。
  - [ ] 前端调用后端 `/calc/income` 成功返回结果。
- [ ] 写一个 README，说明怎么启动前后端。

---

## 3. M1：计算引擎硬化

- [ ] 从 `index.html` 抽出联邦税率：`FED`。
- [ ] 从 `index.html` 抽出标准扣除：`STD`。
- [ ] 从 `index.html` 抽出州税规则：CA、NY、IL、MA、CO、GA、TX、FL、WA、NV。
- [ ] 实现 `bracket_tax()`。
- [ ] 实现 `federal_income_tax()`。
- [ ] 实现 `state_income_tax()`。
- [ ] 实现 `fica_tax()`，包含社保上限、Medicare、>$200K 附加 Medicare。
- [ ] 实现 `foreign_tax_estimate()`，并明确这是简化模型。
- [ ] 实现 `rsu_tax_estimate()`。
- [ ] 实现 `self_employment_tax()`。
- [ ] 实现 `feie_estimate()`。
- [ ] 实现 `crypto_gain_estimate()`。
- [ ] 实现 `nexus_estimate()`。
- [ ] 每个函数返回：`input`、`tax`、`breakdown`、`rule_version`、`citations`、`assumptions`。
- [ ] 所有引擎函数不读 DOM、不读 localStorage、不依赖浏览器。

---

## 4. M1 黄金测试集

- [ ] W-2 普通收入：single，收入 $120,000，401k $15,000。
- [ ] 边界测试：收入刚好低于 $200,000。
- [ ] 边界测试：收入刚好高于 $200,000，触发附加 Medicare。
- [ ] 零州税：TX/FL/WA/NV。
- [ ] 加州累进税。
- [ ] 纽约累进税。
- [ ] RSU 归属收入 + 普通收入合并。
- [ ] 自雇净收入 + SE tax。
- [ ] FEIE 330 天达标。
- [ ] FEIE 330 天不达标。
- [ ] Crypto FIFO/HIFO/LIFO 对比。
- [ ] 电商 Nexus 接近阈值。
- [ ] 电商 Nexus 已触发阈值。
- [ ] 前端原型输出与 Python 引擎输出一致。

---

## 5. M1 FastAPI 最小接口

- [ ] `GET /health`
- [ ] `POST /calc/income`
- [ ] `POST /calc/rsu`
- [ ] `POST /calc/self-employment`
- [ ] `POST /calc/feie`
- [ ] `POST /calc/crypto`
- [ ] `POST /calc/nexus`
- [ ] API 返回统一错误格式。
- [ ] API 返回规则版本。
- [ ] API 返回 citation 列表。
- [ ] OpenAPI 文档可访问。

---

## 6. 前端最小改造

- [ ] 保留现有 UI，不急着迁 Next.js。
- [ ] 把收入税计算按钮改成调用 `/calc/income`。
- [ ] 把 RSU 计算改成调用 `/calc/rsu`。
- [ ] 把自雇税计算改成调用 `/calc/self-employment`。
- [ ] 把 FEIE 计算改成调用 `/calc/feie`。
- [ ] 把加密计算改成调用 `/calc/crypto`。
- [ ] 把 Nexus 计算改成调用 `/calc/nexus`。
- [ ] 页面显示后端返回的 breakdown 和 citation。
- [ ] 删除或停用前端重复计算逻辑。

---

## 7. M2 以后再做

- [ ] PostgreSQL 用户、档案、计算记录。
- [ ] 审计日志：输入 + 规则版本 + 法条 + 输出。
- [ ] 真实 Google OAuth。
- [ ] 真实 Apple Sign in。
- [ ] 真实微信扫码登录。
- [ ] ChromaDB + NetworkX GraphRAG。
- [ ] Copilot 调用税务引擎工具。
- [ ] 金额 Guardrail。
- [ ] Shopify/Amazon 真实 OAuth。
- [ ] W-2/1099 OCR。
- [ ] 自有模型、LoRA、vLLM。
- [ ] Trace 回流和 Eval Harness。
- [ ] GDPR/CCPA、安全、OpenTelemetry。

---

## 8. 第一轮验收标准

- [ ] 新用户可以打开前端页面。
- [ ] 后端 `/health` 正常。
- [ ] 前端至少一个税务计算模块通过 API 返回结果。
- [ ] 黄金测试全部通过。
- [ ] 每个金额结果能看到规则版本和引用来源。
- [ ] README 可以让别人按步骤跑起来。
