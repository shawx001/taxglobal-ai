# Step 5.7 设计文档 — Nexus 前端接 `/calc/nexus`(真实阈值 + 诚实化)

日期：2026-06-02
阶段：PLM 阶段 2（Design）
依据：引擎 `nexus_estimate`(已在 main)、`/calc/nexus` + `NexusRequest`(已就绪)、现有前端范式、REQ-003 诚实化
分支：`feature/step5_7-nexus-frontend`(基于 main)
角色：Claude 出设计 + Codex prompt;Codex 实现、开 PR、合并;Shaw 拍板。

> 目标:把 ecom「各州 Nexus 监控」从**硬编码阈值 + 前端假算**切到后端 `nexus_estimate`:用引擎的**真实州阈值 + exceeded/approaching/status_label + 引用**驱动每州的进度条/预警。**删掉编造的"应缴税额"**(7.25% 拍脑袋 = 假数,违反"不给假数";nexus 是注册义务、非税额)。未覆盖州诚实标"未覆盖",不再套用默认 500K 假阈值。根 `index.html` 冻结;不改引擎/后端/数据。

---

## 0. 范围 + 现状问题
现状 `renderNexus`(frontend/index.html ~L1813):
- 各州销售 `aggState`(单位 **$K**)对**硬编码 `STATE_THR[st]||500`**(单位 $K)算 pct/颜色/周数;
- 预警框编造 **`owed = sales*1000*0.0725`**(假税额);未知州默认套 500K 阈值。
本步:
- **前端 `api.js`**:加 `nexus(payload)` → `postCalc("/calc/nexus", payload)`。
- **前端 `renderNexus`**:每个"需自行申报"的州**并发调 `/calc/nexus`**(sales 由 $K×1000 转 $),用引擎返回:`threshold.sales_amount`(真实阈值)、`status_label`(triggered/approaching/below)、`exceeded`/`approaching`、`citations`。进度条/百分比/颜色基于**真实阈值**;预警基于 `status_label`。
- **诚实化**:① **删除 `$owed` 假税额**(改为"已触发→建议尽快注册该州销售税账户"的合规提示,不报具体税额,因为 nexus_estimate 不算税额);② 未覆盖/`source_pending` 州 → 显示"该州 nexus 规则未覆盖,未做判定",**不套默认阈值**;③ "约 N 周后触发"若保留,必须明确标"**按 YTD 平均的粗略外推,非阈值判定**"(引擎不提供周数);建议保留但加此标注,或直接去掉。
- **不动**:引擎/后端/数据(`/calc/nexus`+`NexusRequest`(state_code/sales_amount/transaction_count)已够)、根 index.html、其它模块。

## 1. `frontend/api.js`
```js
nexus: function (payload) { return postCalc("/calc/nexus", payload); },
```

## 2. `renderNexus` 改造(async,并发每州一调)
```
async function renderNexus(){
  ...(连接判断、aggState 不变)...
  const sellerAgg = aggState(true);                 // {州: 销售$K}
  const states = Object.keys(sellerAgg);
  // 每州调引擎(sales $K -> $);tx 数若 store 数据有则传,否则不传
  const results = await Promise.all(states.map(st =>
     TaxGlobalApi.nexus({ state_code: st, sales_amount: Math.round(sellerAgg[st]*1000) /*, transaction_count: 若有*/ })
       .then(resp => ({ st, sales: sellerAgg[st], resp }))
       .catch(() => ({ st, sales: sellerAgg[st], resp: null }))   // 单州失败不拖垮整表
  ));
  // 渲染每行:
  //   覆盖(resp.status==='ok'): thr$K = resp.result.threshold.sales_amount/1000;
  //     pct = sales/thr*100; status_label 决定颜色/文案(triggered=红/已触发;approaching=金/接近;below=绿/安全);
  //     引用用 taxCitations(resp.citations)。
  //   未覆盖(resp.status==='not_covered' 或 resp 为 null): 行显示"该州 nexus 规则未覆盖,未做判定"(灰),不算 pct、不套假阈值。
  // 预警框:取 status_label==='triggered' 或 'approaching' 的州;文案"建议尽快注册该州销售税账户"——
  //   不显示任何"应缴税额"(已删假数)。
  // 指标卡:已触发数 = status_label==='triggered' 计数;接近数 = 'approaching' 计数(都来自引擎,不前端自判)。
}
```
- 金额/阈值/状态全取引擎返回;前端只做 $K↔$ 换算与展示。
- `weeksLeft` 若保留:`Math.max(1, Math.round((thr-sales)/(sales/26)))` 仅当 below/approaching 时显示,且标注"粗略外推"。

## 3. 验收(退出门槛)
- [ ] **headless 复现**(httpx 走 `/calc/nexus` + 读 renderNexus 逻辑):
  - CA sales $600K → `/calc/nexus {state_code:CA, sales_amount:600000}` → `exceeded:true`、`status_label:triggered`、`threshold.sales_amount:500000`;前端该行红/已触发、阈值显示 $500K。
  - CA sales $450K → `approaching`(≥80%×500K);below 用更低值。
  - 未覆盖州(如某 source_pending/不存在州)→ not_covered → 行显示"未覆盖",无 pct、无假阈值。
- [ ] **不再有任何编造税额**(grep 确认 `0.0725`/`owed` 假算已删);未覆盖州不套默认阈值。
- [ ] 单州调用失败不影响其它州(catch 兜底)。
- [ ] **根 index.html hash 未变**;改动仅限 ecom/nexus 模块 + api.js。
- [ ] `python -m unittest discover -s tests`、`ruff`、`pip-audit`、`validate_step1_data.ps1`、`git diff --check` 全绿(本步无引擎/后端/数据改动,测试集不变)。
- [ ] Claude **逐行**(5 维)review + headless 复现 + 确认无假数 + 根 hash。

## 4. 交付物与分工
- **Codex**:`frontend/api.js`(+nexus);`frontend/index.html`(renderNexus 改 async 调后端 + 删假税额 + 未覆盖诚实 + 调用点 `await`);更新 `feature_status.md`(Nexus 前端接后端/Step 5.7)、`product_backlog.md`(REQ-003 进展:Nexus 已迁;6国对比/W-2 仍待)。设计(本文件)+ 交付记录 `docs/step5_7_nexus_frontend.md`。分支 `feature/step5_7-nexus-frontend`,PR→main,CI 绿。
- **Claude**:本设计 + Codex prompt;实现后逐行 review + headless 复现(CA 触发/接近/未覆盖)+ grep 确认无假税额 + 根 hash。
- **Shaw**:拍板、合并。

## 5. 之后
REQ-009(全收入合并计税)、REQ-003 收尾(6 国对比 `usTaxTotal`/W-2 迁移后删 `caStateTax/nyStateTax`)、知识库(Step 6+)。
注:`renderNexus` 是 dashboard(多州),改成 async 后所有调用点(`go('ecom')`/连接平台后)需 `await` 或容忍 Promise;Codex 注意调用点。
