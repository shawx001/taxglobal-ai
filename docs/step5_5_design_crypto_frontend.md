# Step 5.5 设计文档 — 加密前端接 `/calc/crypto`(逐笔成本 + 三法对比,真引擎)

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：Step 2.2 引擎 `crypto_gain_estimate`（已在 main，已核准确）、`/calc/crypto` + `CryptoRequest`（已就绪）、现有前端范式（calcSE/calcTax + taxBlock/taxMoney/taxCitations/taxAssumptions）、Claude 对 crypto 引擎的准确性复核结论
分支：`feature/step5_5-crypto-frontend`（基于 main）
角色：Claude 出设计 + Codex prompt；Codex 实现、开 PR、合并；Shaw 拍板。

> 目标：把前端「加密」模块从**单字段假算**（`cr-proceeds` × 假乘数 `CM{0.55/0.78/0.68}×0.4×0.20`）换成**真引擎**：逐笔 **lots/disposals 录入** → 调 `/calc/crypto` → 展示 realized 短/长期利得、**8949 逐笔行**、税额（短期普通增量 + LTCG stacking + NIIT）、**FIFO/LIFO/HIFO 三法对比选最省**。**显著标注诚实边界(仅联邦+NIIT、不含州税)**。**根 `index.html` 冻结不动**；**不改后端/引擎/数据**。

---

## 0. 范围
- **不改后端/引擎/数据**：`/calc/crypto` + `CryptoRequest`(lots/disposals/method/filing_status/other_taxable_income/**modified_agi**)已支持全部所需。
- **`frontend/api.js`**：`TaxGlobalApi` 加 `crypto(payload)` → `postCalc("/calc/crypto", payload)`（method 后端会 .upper()，前端传大写即可）。
- **`frontend/index.html`**（仅 crypto 模块 `pg-crypto` + `calcCrypto`）：
  - 删除假算：`CM` 乘数表、`cr-proceeds` 单字段路径。
  - 新增 **lots（买入批次）/ disposals（卖出）逐行录入** + filing/其他普通应税收入/**modified_agi** 输入 + 三法切换。
  - 重写 `calcCrypto` 为 async，调真引擎并渲染。
- **不动**：根 `index.html`（冻结）、其它前端模块、引擎、数据。

## 1. `frontend/api.js`
```js
crypto: function (payload) { return postCalc("/calc/crypto", payload); },
```

## 2. 前端表单（crypto 面板，替换现 L812-815）
**lots 录入**（重复行，每行：资产/取得日/数量/总成本基）+ **disposals 录入**（每行：资产/卖出日/数量/总收入）。MVP 用一个简单 add/remove 行结构;**默认预填一组可算的示例**(= 引擎设计数据集 D，打开即出结果):
- lots 默认两行：BTC 2023-01-10 数量 1 成本 20000；BTC 2024-06-01 数量 1 成本 40000。
- disposals 默认一行：BTC 2025-03-01 数量 1.5 收入 75000。
其它输入:
- `cr-filing`（single/mfj/hoh，onchange=calcCrypto）
- `cr-method`（FIFO/LIFO/HIFO 切换;同时三法都会算用于对比，这里选“看哪个的明细”）
- `cr-other`（其他普通应税收入，用于税档 stacking，默认 0）
- `cr-magi`（modified AGI，用于 NIIT 精确;**留空则不传**，引擎按近似并在 assumptions 标注）
每个输入 oninput/onchange = calcCrypto；add/remove 行后也调 calcCrypto。

## 3. `calcCrypto` 重写（async，三法对比，复用现有渲染件）
```
let cryptoRequestSeq = 0;
async function calcCrypto(){
  const requestId = ++cryptoRequestSeq;
  const lots = 读所有 lot 行 -> [{asset,date,quantity:Number,cost_basis:Number}]（过滤空行）
  const disposals = 读所有 disposal 行 -> [{asset,date,quantity,proceeds}]
  if(lots.length<1 || disposals.length<1){ 提示“至少一笔买入和一笔卖出”; return; }
  const filing = cr-filing.value, other = +cr-other||0;
  const magiRaw = cr-magi.value; const magi = magiRaw==='' ? undefined : (+magiRaw||0);
  const base = { lots, disposals, filing_status:filing, other_taxable_income:other };
  if(magi!==undefined) base.modified_agi = magi;
  cryptoResult.innerHTML = calculating...;
  try{
    const methods = ['FIFO','LIFO','HIFO'];
    const results = await Promise.all(methods.map(m => TaxGlobalApi.crypto({...base, method:m})));
    if(requestId !== cryptoRequestSeq) return;
    const byMethod = {}; methods.forEach((m,i)=>byMethod[m]=results[i]);
    // 对比条：每法 total = result.result.tax_estimate.total;高亮最小（最省）
    // 明细：取当前 cr-method 选中法的 result 渲染:
    //   realized 短/长期利得;tax_estimate(短期普通税/LTCG/NIIT/total);每季度可不做(本函数无 quarterly)
    //   8949 逐笔行:result.result.lots_matched[] -> 资产/数量/acquired/sold/proceeds/cost_basis/gain/term
    //   taxCitations(result.citations) + taxAssumptions(result.assumptions)
    cryptoResult.innerHTML = 对比条 + 明细 + 8949 表 + 诚实横幅(见 §4) + assumptions;
  }catch(error){
    if(requestId !== cryptoRequestSeq) return;
    // oversell/坏数据 -> 后端 422 invalid_input,error.message 即引擎 reason(如 "Disposal quantity ... exceeds...")
    cryptoResult.innerHTML = alert(error.code==='service_unavailable'?backendDown:error.message);
  }
}
```
关键点：
- **三法都用真引擎算**（Promise.all 三次调用），对比条显示各法 total 并高亮最省 → 取代假乘数，真实节税卖点。
- 金额一律取引擎 `result.*`，前端不再二次算税、不再用 `CM` 乘数。
- 8949 行直接来自 `lots_matched`（逐笔、真实），兑现“自动生成 Form 8949”的展示（仅展示行，不生成 PDF——PDF 导出仍属范围外，见 assumptions）。

## 4. 诚实边界（显著展示，源于 Claude 准确性复核）
- **🔴 州税横幅(必须显著)**:“本测算为**联邦资本利得 + NIIT**;**不含州税**。多数州把资本利得按普通收入征(如 CA 最高 13.3%、WA 对长期资本利得另有 7%/超百万 9.9% excise)。”——这是最大的“看起来准其实缺一半”风险，必须在结果区顶部醒目展示，不能只埋在 assumptions。
- **NIIT 口径**:提供 `cr-magi` 才精确;留空时引擎用近似并在 assumptions 标注，UI 同步提示“填 modified AGI 可让 NIIT 更准”。
- **NFT 收藏品**:被认定为 collectible 的 NFT 适用最高 28%,本测算按普通加密 0/15/20% → UI/assumptions 标注。
- **净亏**:净资本亏损时税显示 0,并展示引擎的“$3,000 抵扣/结转需整表上下文,本函数不算”说明。
- 这些大多已在引擎 `assumptions` 里;州税横幅是前端**额外**加的醒目提示。

## 5. 约束
- **根 `index.html` 不得改动**（hash 恒为 `833508998A7FF1C783646E5E8B35E8C66AB27AE5FF88193318C2A1F2007B4B69`,验收必查）。
- 只改 `frontend/api.js` + `frontend/index.html`(crypto 模块);**不改后端/引擎/数据/其它前端模块**。
- profile 同步:crypto 的 lots/disposals 直接在模块录入,**本步不接 `profile.cryptoGain`**（单数字无法表达逐笔批次;避免 SE 那种共享 sync 复杂度）。`profile.cryptoGain` 维持现状给 dashboard 用。

## 6. 验收(退出门槛)
- [ ] **headless 复现**(httpx 走 `/calc/crypto` + 读 calcCrypto 渲染字段):
  - 数据集 D + FIFO + other=100000 + single → realized ST 5000 / LT 30000;tax_estimate total **5633.00**(st 1133 / ltcg 4500 / niit 0)。
  - 三法对比:FIFO realized 合计 35000 vs HIFO/LIFO 25000;**HIFO total < FIFO total**(对此数据集 HIFO 更省;具体分值我 review 时逐分核)。
  - 超卖(卖>买)→ 端点 422,UI 显示引擎 reason(含 "exceeds")。
- [ ] `calcCrypto` 不再使用假乘数 `CM`/`cr-proceeds` 路径(grep 确认 `mult` 假算已删)。
- [ ] **州税横幅**在结果区顶部醒目展示;NFT/NIIT/净亏 提示到位。
- [ ] **根 `index.html` hash 未变**;`frontend/index.html` 改动仅限 crypto 模块。
- [ ] `python -m unittest discover -s tests`、`ruff check engine backend tests`、`pip-audit`、`validate_step1_data.ps1`、`git diff --check` 全绿(本步无引擎/后端改动,测试集不变)。
- [ ] Claude **逐行** review([Blocker]/[Major]/[Minor]/[Nitpick]):payload 字段对、金额全取引擎、三法对比真实、错误/竞态处理、州税横幅诚实、根 hash。

## 7. 交付物与分工
- **Codex**：`frontend/api.js`(+crypto)、`frontend/index.html`(crypto 模块:lots/disposals 录入 + filing/other/magi + 三法切换 + 重写 calcCrypto + 删假算);更新 `feature_status.md`(D 模块加 Step 5.5 加密前端)、`product_backlog.md`(crypto 州税缺口记为新 REQ/待办);设计(本文件)+ 交付记录 `docs/step5_5_crypto_frontend.md`。分支 `feature/step5_5-crypto-frontend`,PR→main,CI 绿。
- **Claude**：本设计 + Codex prompt;实现后逐行 review + headless 复现(5633 / 三法对比 / 超卖 422)+ 州税横幅核验 + 根 hash。
- **Shaw**：拍板、确认合并。

## 8. 之后
- **新 REQ(建议)**:crypto 接州税(多数州按普通收入征资本利得;CA/WA 特殊)——这是“算得准”的下一块大头,需引擎/数据支持后再做。
- Step 5.6 Nexus 前端接 `/calc/nexus`;REQ-003 完整闭环(删 caStateTax/nyStateTax)待 6 国对比/W-2 模块迁移。
