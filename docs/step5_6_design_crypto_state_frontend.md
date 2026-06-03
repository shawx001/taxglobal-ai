# Step 5.6 设计文档 — 加密前端显示「州税」(REQ-012 前端) + 引擎小清理

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：Step 2.6 引擎(crypto `state_code` + `state`/`total_tax_including_state`,已在 main)、Step 5.5 crypto 前端、现有前端范式
分支：`feature/step5_6-crypto-state-frontend`(基于 main)
角色：Claude 出设计 + Codex prompt;Codex 实现、开 PR、合并;Shaw 拍板。

> 目标:把 Step 2.6 已算准的**加密州税**显示到前端。crypto 模块加 `cr-state` 选择器 → 调 `/calc/crypto` 时带 `state_code` → 展示引擎返回的 `state`(类型/税额)与 `total_tax_including_state`,并按州类型**诚实分流**渲染。三法对比在选了州后按**含州税总额**排"最省"。**顺带把上一轮漏提交的引擎小清理一并做掉**(见 §3)。根 `index.html` 冻结;不改引擎计算逻辑(只清理)。

---

## 0. 范围
- **前端 `frontend/index.html`(仅 crypto 模块)**:加 `cr-state` 选择器;`calcCrypto` payload 带 `state_code`;渲染州税 + 含州总税 + 按州类型分流的诚实文案;三法对比按含州税总额排序。
- **前端 `frontend/api.js`**:无需改(`crypto(payload)` 已透传;只是 payload 多带 `state_code`)。
- **引擎小清理(REQ-012 收尾,折进本 PR)**:见 §3。
- **不动**:根 `index.html`、引擎**计算逻辑**、数据、其它前端模块。

## 1. 表单(crypto 输入区,与 cr-filing/cr-method/cr-other/cr-magi 同组)
加 `cr-state` 选择器(默认"不计州税"→不传 state_code,行为同现状):
```html
<div class="field"><label class="flabel">所在州（资本利得州税）</label>
  <select class="sel" id="cr-state" onchange="calcCrypto()">
    <option value="">（不计州税）</option>
    <option value="CA">加州 CA</option><option value="NY">纽约 NY</option>
    <option value="GA">乔治亚 GA</option><option value="IL">伊利诺伊 IL</option>
    <option value="CO">科罗拉多 CO</option>
    <option value="WA">华盛顿 WA（长期 excise）</option>
    <option value="FL">佛州 FL（无所得税）</option><option value="NV">内华达 NV（无所得税）</option>
    <option value="TX">德州 TX（暂未覆盖）</option><option value="MA">马萨诸塞 MA（暂未覆盖）</option>
  </select></div>
```

## 2. `calcCrypto` 改动(payload + 排序 + 渲染)
- **payload**:`const stateCode=document.getElementById('cr-state').value; if(stateCode) base.state_code=stateCode;`(空=不传→无 state 块,保持现状)。
- **三法"最省"排序**:选了州时按 `result.total_tax_including_state` 排序(含州税才是真总税);未选州时仍按 `tax_estimate.total`。
  - `const methodTotal = p => p.result.total_tax_including_state!=null ? Number(p.result.total_tax_including_state) : Number(p.result.tax_estimate.total);`
  - `totals`、`minTotal`、`cheapestMethods`、卡片显示金额都用 `methodTotal`(留 `Number.isFinite` 守卫,沿用现有抛错风格)。
- **渲染(`cryptoResultBlock`)**:在"联邦+NIIT 总税"行后,按 `r.state`(可能不存在)插入州税区:

| `r.state` 情况 | 展示 |
|---|---|
| 无(未选州) | 现状横幅"仅联邦+NIIT,不含州税" + 仅联邦总税 |
| `status==='not_covered'`(MA/TX/未知) | 金色诚实条:"该州({state})州税未覆盖,以下仅联邦+NIIT"(可带 `reason`);总税仅联邦 |
| `type==='no_state_income_tax'`(FL/NV) | 注:"该州无个人所得税,加密利得州税 $0";州税行 $0;含州总税=联邦 |
| `type==='excise'`(WA) | "州资本利得 excise（仅长期）"行=`state.tax`;副行展示 `long_term_gain` / `standard_deduction` / `taxable_washington_capital_gain` / `rate`;注"短期不计";含州总税行 |
| `type==='ordinary_income'`(CA/NY/GA/IL/CO) | "州所得税（资本利得按普通收入）"行=`state.tax`;含州总税行 |
- 覆盖州(ordinary/excise/none)显示 **"总税（联邦+NIIT+州）"= `r.total_tax_including_state`**。
- 选了覆盖州后,把顶部"仅联邦+NIIT 不含州税"横幅替换为含州税的完整结果(不再误导);WA 仍显著标"仅长期 excise";not_covered/未选州 保留诚实提示。
- 金额一律取引擎 `r.state.*` / `r.total_tax_including_state`,前端不二次算税。

> 注:WA `state` 块的长期利得字段为 **`long_term_gain`**(见 §3 改名);前端读 `state.long_term_gain`。

## 3. 引擎小清理(REQ-012 收尾,Shaw 上轮漏提交,折进本 PR — 非单独 PR)
纯重构,**不改任何计算结果**(我已确认 golden/测试不引用被改字段,改后 59 测试不变):
1. 抽 `_crypto_state_not_covered(code, reason, citations=None) -> (dict, citations, assumptions)`,把 `_crypto_state_tax` 里 **5 处** not_covered 字面字典替换为调用它(去重)。
2. WA excise 结果字段 `taxable_long_term_gain` **改名 `long_term_gain`**(更准:它存的是毛长期利得;扣除后量在 `taxable_washington_capital_gain`)。`grep` 确认仅 `engine/tax_engine.py` 引用,无 golden/测试需改。

## 4. 验收(退出门槛)
- [ ] **headless 复现**(httpx 走 `/calc/crypto` 带 state_code + 读 calcCrypto 渲染字段):数据集 D FIFO、other=100000、single:
  - CA → `state.tax 3255.00`、`total_tax_including_state 8888.00`;GA → 1816.50/7449.50;WA(LT 30000)→ 0;FL → 0/no_state_income_tax;MA → not_covered。
  - WA 大额(净 LT 500000)→ `state.type excise`、`state.tax 15540.00`。
- [ ] 三法对比:选州后按含州税总额排"最省";未选州按联邦总额(回归)。
- [ ] 未选州(空 state_code)→ 无 state 块、行为同现状(横幅"不含州税")。
- [ ] 引擎清理:`_crypto_state_not_covered` 抽出、5 处替换;`long_term_gain` 改名;**59 测试不变**、golden 值不变。
- [ ] **根 index.html hash 未变**;`frontend/index.html` 改动仅限 crypto 模块。
- [ ] `python -m unittest discover -s tests`、`ruff`、`pip-audit`、`validate_step1_data.ps1`、`git diff --check` 全绿。
- [ ] Claude **逐行**(5 维)review + headless 复现 + 确认引擎计算结果未变 + 根 hash。

## 5. 交付物与分工
- **Codex**:`frontend/index.html`(crypto 模块:+cr-state、calcCrypto payload/排序/渲染);`engine/tax_engine.py`(§3 清理);更新 `feature_status.md`(REQ-012 完成:引擎+数据+前端)、`product_backlog.md`(REQ-012 → ✅);设计(本文件)+ 交付记录 `docs/step5_6_crypto_state_frontend.md`。分支 `feature/step5_6-crypto-state-frontend`,PR→main,CI 绿。
- **Claude**:本设计 + Codex prompt;实现后逐行 review + headless 复现(CA 8888 / WA excise / not_covered 诚实)+ 确认 §3 清理不改数值 + 根 hash。
- **Shaw**:拍板、合并。

## 6. 之后
**Step 5.7**:Nexus 前端接 `/calc/nexus`(最后一个原型假算模块)。再后:REQ-009 全收入合并计税、REQ-003 收尾(删 `caStateTax/nyStateTax`)、知识库(Step 6+)。
