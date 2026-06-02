# Step 5 设计文档 — 前端接后端（个人所得税模块先跑通）

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：`engineering_process.md`、`coding_standards.md`、Step 4 FastAPI、`product_backlog.md`
分支：`feature/step5-frontend-api`
角色：Claude 出设计 + 评审；Codex 实现。

> 目标：让 `frontend/index.html` 的**个人所得税模块**不再自己用 JS 算，而是调用 Step 4 的后端 API，展示后端返回的真实税额 + 法条 + 明细；没数据的州诚实提示；后端不可用时明确报错。**本步只接个人所得税一个模块**(联邦+FICA+州)，其余模块(RSU/自雇/FEIE/加密/Nexus)维持原型行为，后续逐个接。**不改档案结构**(REQ-001 留后续)。

---

## 1. 重要前提(和前面步骤不同)

- **两份 index.html 在本步"分家"——计划内**。`frontend/index.html`(工作副本)开始调后端;**根目录 `index.html` 保持冻结**(原型参照,不动)。
- 因此"两份 hash 一致"校验**到此终止**;改为校验:**根目录 `index.html` 仍等于已知冻结 hash `833508998A7FF1C783646E5E8B35E8C66AB27AE5FF88193318C2A1F2007B4B69`**。
- 后端需加**开发用 CORS**(前端页面跨端口调 `:8000`);生产 CORS 策略仍属后续。

## 2. 后端改动(小)
- `backend/main.py`:加 `CORSMiddleware`,开发配置允许本地来源(如 `http://127.0.0.1`、`http://localhost` 及常见静态端口)。**标注为 dev 配置**,生产收紧留后续。
- `tests/test_api_calc.py`:加一条断言,带 `Origin` 的预检/请求返回正确 CORS 头。

## 3. 前端改动(个人所得税模块)
建议新增 `frontend/api.js`(后端调用封装)+ 在 `frontend/index.html` 改个人所得税模块的计算路径;其余 UI 不动。

**计算流程(前端只编排展示,真计算在后端):**
1. 收集输入:gross_income、filing_status、state_code、deduction?
2. 依次调用(1:1 接口,Step 4 决定不做合并接口):
   - `POST /calc/federal-income` → 得 federal tax + taxable_income + citations
   - `POST /calc/fica`(wages=工资性收入) → 得 FICA
   - `POST /calc/state-income`(taxable_income 用上一步联邦返回的 taxable_income) → 得州税或 not_covered
3. 展示:联邦税、FICA、州税三块,各自显示 **税额 + breakdown + citations + assumptions**;总额 = 三者之和(对权威数字做加总，非税务计算)。

**关键体验(诚实、不伪装):**
- **没数据的州**(state 返回 `status: not_covered`)→ 该块显示"该州暂无官方法规数据,无法计算"+ reason;**不显示州税数字、不影响联邦/FICA 展示**。
- **后端不可用**(fetch 失败/网络错/非 2xx 非预期)→ 明确显示"后端服务不可用,无法计算",**绝不回退到旧的前端假算或显示陈旧数字**。
- **422**(如校验失败/unsupported_tax_year)→ 展示后端返回的 error.message。
- 每个税额旁显示其 `citations`(法条来源),呼应"每个结论可追溯"。
- **移除/停用该模块原有的前端税额计算 JS**(不再重复算);其余模块的旧 JS 暂留(它们还没接后端)。

## 4. 设计决策(已拍板)
- **S5-1** 个人所得税 = 3 次接口调用(联邦/FICA/州),前端编排展示 + 加总;不新增合并接口(合并总览待 `income_tax_summary`)。
- **S5-2** 州税的 taxable_income 暂用联邦返回的 taxable_income(MVP 近似,assumption 标注;各州自有应税口径留后续)。
- **S5-3** CORS 用开发配置(允许本地),生产策略后续。
- **S5-4** 根 `index.html` 冻结、`frontend/index.html` 分家;验收从"两份一致"改为"根未变 + 前端走 API"。
- **S5-5** API 不可用 / not_covered 一律诚实提示,不回退假算、不显示陈旧值。

## 5. 验收与测试(诚实说明测试边界)
- **后端**:CORS 头有 → API 测试覆盖。
- **前端**:目前无 JS 自动化测试框架(Playwright/Selenium 未引入)。本步前端行为以**真实浏览器手动/可视验证**为主:
  - 打开 `frontend/index.html`,个人所得税模块输入收入+州+身份 → 显示后端真实税额 + 法条。
  - 选 CA → 显示"无法计算 + 原因"(not_covered)。
  - 停掉后端 → 显示"服务不可用"。
  - 选 IL/CO/GA/FL 等有数据州 → 正常出数。
- Claude review 时会**实际驱动页面**(浏览器)确认上述行为,不只看代码。
- 前端 JS 自动化测试框架作为**后续基建**(本步先列为已知限制,不假装已覆盖)。
- 根 `index.html` hash 未变;`validate_step1_data.ps1`、engine/backend 测试仍全绿。

## 6. 交付物与分工
- **Codex**:`backend/main.py`(加 CORS)、`tests/test_api_calc.py`(CORS 断言);`frontend/api.js`、改 `frontend/index.html` 个人所得税模块;`docs/step5_design_frontend.md` 一并提交;交付记录 `docs/step5_frontend_api.md`。**不动根 index.html、不动其余模块计算逻辑、前端不写税额计算**。分支 `feature/step5-frontend-api`,PR 到 main,CI 绿。
- **Claude**:本设计;实现后**实际开浏览器**验证 4 个场景(正常出数 / CA not_covered / 后端关闭 / 法条展示)+ 查前端无重复税额计算 + 根 index.html 未变。
- **Shaw**:合并 PR。

## 7. 退出门槛
- [ ] 个人所得税模块完全由后端返回(联邦+FICA+州),显示税额+法条+明细。
- [ ] CA/NY 等无数据州显示诚实"无法计算+原因",不出假数。
- [ ] 后端关闭时前端明确提示"服务不可用",不回退假算。
- [ ] 前端不再重复做个人所得税计算(grep 该模块路径确认)。
- [ ] CORS 开发配置可用;CI 全绿;根 `index.html` hash 未变。
- [ ] Claude 浏览器实测通过 + [Blocker]/[Major]/[Minor] 评审通过。

## 8. 范围外(已知限制)
其余模块(RSU/自雇/FEIE/加密/Nexus)仍走原型旧算法(后续逐个接);档案"美国/海外"分桶(REQ-001)、档案点开同步(REQ-002 的持久化部分)、Next.js 迁移、账号、前端 JS 自动化测试框架、生产 CORS——均属后续。
