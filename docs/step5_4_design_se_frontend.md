# Step 5.4 设计文档 — 自雇前端接 `income_tax_summary`（联邦+SE+州全精确）

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：Step 2.5 引擎 `income_tax_summary`(已在 main)、现有前端 API 范式(`frontend/api.js` + 已迁移模块 calcTax/calcRSU/calcFEIE)、REQ-002(档案→计算)、REQ-003(删前端州税函数)
分支：`feature/step5_4-se-frontend`(基于 main)
角色：Claude 出设计 + Codex prompt;Codex 实现、开 PR、合并;Shaw 拍板。

> 目标：把前端「自雇税」模块从**原型假算**(`calcSE` 裸写 SE 公式 + 硬编码 `caStateTax`)切换到后端 **`income_tax_summary`**,展示**联邦+SE+精确州税**的完整自雇总税 + 季度预缴,带引用/假设/not_covered 诚实提示。新增后端端点 `/calc/income-summary` 暴露引擎。**根 `index.html` 冻结不动**;`caStateTax/nyStateTax` 本步**不删**(仍被未迁移模块用,见 §5)。

---

## 0. 范围
- **后端**:新增 `POST /calc/income-summary` 端点 + `IncomeSummaryRequest` schema,薄封装 `income_tax_summary`(沿用 `_call_engine`/状态映射)。**不改引擎**。
- **前端 `frontend/api.js`**:`TaxGlobalApi` 加 `incomeSummary(payload)` → `postCalc("/calc/income-summary", payload)`。
- **前端 `frontend/index.html`**:
  - 自雇表单(现 L620-622:净自雇收入 `se-net`/业务支出 `se-exp`/SEP-IRA `se-sep`)**新增**「所在州 `se-state`」「申报状态 `se-filing`」两个 `<select>`(选项复用 income-tax 模块 L556-574)。
  - **重写 `calcSE`**(L1472)为 async,照 `calcTax` 范式调后端、渲染。
- **不动**:根 `index.html`(冻结)、引擎、数据、其它前端模块。

## 1. 后端端点 + schema
`backend/schemas.py` 新增(字段对齐 `income_tax_summary` 入参;数值 `ge=0`;`filing_status` 用现有 `FilingStatus`):
```python
class IncomeSummaryRequest(TaxYearModel):
    net_self_employment_profit: float = Field(default=0, ge=0)
    other_ordinary_income: float = Field(default=0, ge=0)
    filing_status: FilingStatus = "single"
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    se_health_insurance: float = Field(default=0, ge=0)
    retirement_contributions: float = Field(default=0, ge=0)
    qbi_w2_wages: float = Field(default=0, ge=0)
    qbi_ubia: float = Field(default=0, ge=0)
    is_sstb: bool = False
    deduction: float | None = Field(default=None, ge=0)
```
`backend/routes/calc.py`:import `income_tax_summary`;加
```python
@router.post("/calc/income-summary", response_model=None)
def calc_income_summary(payload: IncomeSummaryRequest, request: Request):
    return _call_engine(request, income_tax_summary, **payload.model_dump())
```
状态映射沿用现有:`ok`→200(州 not_covered 是**嵌套**在 `result.state_income_tax` 里,顶层仍 `ok`)、`invalid_input`(如非法 filing)→422、`RuleLoadError`→422。每响应带 `X-Request-ID`、走 CORS。

## 2. 前端表单(自雇面板)
在自雇输入区(`se-net/se-exp/se-sep` 同组)加:
```html
<div class="field"><label class="flabel">所在州（决定州所得税）</label>
  <select class="sel" id="se-state" onchange="calcSE()">
    <option value="CA">加州 CA</option><option value="NY">纽约 NY</option>
    <option value="GA">乔治亚 GA</option><option value="IL">伊利诺伊 IL</option>
    <option value="CO">科罗拉多 CO</option>
    <option value="TX">德州 TX（无所得税）</option><option value="FL">佛州 FL（无所得税）</option>
    <option value="WA">华盛顿 WA（无所得税）</option><option value="NV">内华达 NV（无所得税）</option>
    <option value="MA">马萨诸塞 MA（暂未覆盖）</option>
  </select></div>
<div class="field"><label class="flabel">申报状态</label>
  <select class="sel" id="se-filing" onchange="calcSE()">
    <option value="single">单身申报</option><option value="mfj">已婚联合申报</option>
    <option value="hoh">户主申报</option>
  </select></div>
```
（MA 列出是为演示 not_covered 的诚实提示。）

## 3. `calcSE` 重写(async,照 calcTax 范式,复用 taxBlock/taxMoney/taxCitations/taxAssumptions)
```
let seRequestSeq = 0;
async function calcSE(){
  const requestId = ++seRequestSeq;
  const net = +se-net||0, exp = +se-exp||0, sep = +se-sep||0;
  const payload = {
    net_self_employment_profit: Math.max(0, net - exp),
    retirement_contributions: sep,
    filing_status: se-filing.value,
    state_code: se-state.value,
  };
  seResult.innerHTML = calculating...;
  try {
    const s = await TaxGlobalApi.incomeSummary(payload);
    if (requestId !== seRequestSeq) return;      // 防竞态
    const r = s.result;
    const st = r.state_income_tax;                // {status, tax, not_covered?, reason?}
    const stateCovered = st && st.status === 'ok';
    // 渲染行(taxMoney + 引用):净营业利润、自雇税(§1401)、[附加医保 if>0]、−½SE(§164(f))、
    //   −退休供款、AGI、−标准/指定扣除、QBI(§199A)、应税收入、联邦所得税、
    //   州所得税(taxBlock:stateCovered ? tax : {notCovered:true, reason:st.reason})、
    //   总税额(r.total_tax)、每季度预缴(r.quarterly_estimate,§6654)。
    // 顶部整块用 taxCitations(s.citations) + taxAssumptions(s.assumptions) 展示来源与诚实边界。
    seResult.innerHTML = ...;
  } catch (error) {
    if (requestId !== seRequestSeq) return;
    seResult.innerHTML = alert(error.code==='service_unavailable'?backendDown:error.message);
  }
}
```
关键点:
- **单次调用**即可(引擎已组合联邦+SE+州);不再前端裸算、不调 `caStateTax`。
- 州 `not_covered`(MA)→ 州行显示金色「未覆盖」+ `st.reason`,总税只含联邦+SE(与引擎一致),并由 `s.assumptions` 提示。
- 金额一律用引擎返回的 `result.*` 字段(精确),前端不再二次计算税额。

## 4. `frontend/api.js`
`TaxGlobalApi` 加:
```js
incomeSummary: function (payload) { return postCalc("/calc/income-summary", payload); },
```

## 5. REQ-003(前端遗留州税函数)
- 本步使 `calcSE` **不再使用** `caStateTax/nyStateTax`。
- 但这两个函数仍被 `usTaxTotal`(6 国对比 L1277)、L1609、`stateLookup`(L1136)使用 → **本步不删除**,避免破坏未迁移模块原型。REQ-003 记为**部分完成**(自雇已迁;6 国对比/L1609 待后续步骤迁移时一并删)。

## 6. 约束
- **根 `index.html` 不得改动**(hash 恒为 `833508998A7FF1C783646E5E8B35E8C66AB27AE5FF88193318C2A1F2007B4B69`,验收必查)。
- 只改 `backend/schemas.py`、`backend/routes/calc.py`、`frontend/api.js`、`frontend/index.html`;**不改引擎/数据**。
- 后端端点测试加在 `tests/test_api_calc.py`。

## 7. 验收(退出门槛)
- [ ] **后端端点测试**(`tests/test_api_calc.py`):
  - `POST /calc/income-summary {net_self_employment_profit:100000, filing_status:"single", state_code:"CA"}` → 200,`result.total_tax==27311.11`、`result.state_income_tax.tax==4550.96`、`result.federal_income_tax==8630.60`。
  - `state_code:"FL"` → `total_tax==22760.15`、州 tax 0。
  - `state_code:"MA"` → 顶层 200/ok,`result.state_income_tax.status=="not_covered"`、`total_tax==22760.15`。
  - 非法 `filing_status` → 422 `invalid_input`;响应带 `X-Request-ID`。
- [ ] **headless 复现前端**(httpx 走端点 + 读 `calcSE` 渲染逻辑字段):se-net=100000/exp=0/sep=0、CA、single → 总税 27311.11、季度 6827.78;MA → 州行「未覆盖」、总税 22760.15。
- [ ] `calcSE` 不再调用 `caStateTax/nyStateTax`(grep 确认);`caStateTax/nyStateTax` 仍存在(给未迁移模块)。
- [ ] **根 `index.html` hash 未变**;`frontend/index.html` 改动仅限自雇模块。
- [ ] `python -m unittest discover -s tests`、`ruff check engine backend tests`、`pip-audit -r backend/requirements.txt`、`validate_step1_data.ps1`、`git diff --check` 全绿。
- [ ] Claude review 通过([Blocker]/[Major]/[Minor]/[Nitpick]);重点:端点状态映射、not_covered 诚实渲染、金额全部取引擎字段(前端不二次算税)、根 hash。

## 8. 交付物与分工
- **Codex**:`backend/schemas.py`(+IncomeSummaryRequest)、`backend/routes/calc.py`(+端点)、`frontend/api.js`(+incomeSummary)、`frontend/index.html`(自雇表单 +2 select、重写 calcSE)、`tests/test_api_calc.py`(端点测试);更新 `feature_status.md`(D 模块「前端改调后端」补自雇一行/Step 5.4)、`product_backlog.md`(REQ-002 推进、REQ-003 部分完成);设计(本文件)+ 交付记录 `docs/step5_4_se_frontend.md`。分支 `feature/step5_4-se-frontend`,PR→main,CI 绿。
- **Claude**:本设计 + Codex prompt;实现后独立验(端点重算 27311.11/22760.15、headless 复现、not_covered 诚实、根 hash、grep caStateTax 不再被 calcSE 用)。
- **Shaw**:拍板、确认合并。

## 9. 之后
Step 5.5/5.6:加密(`/calc/crypto`)、Nexus(`/calc/nexus`)前端接后端。REQ-003 完全闭环需等 6 国对比(`usTaxTotal`)/W-2 模块迁移时删 `caStateTax/nyStateTax`。REQ-002:档案数据(州/身份/收入桶)自动带入自雇模块(档案→计算同步)后续步骤实现。
