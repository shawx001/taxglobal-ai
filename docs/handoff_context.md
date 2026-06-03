# 项目交接 / 上下文摘要（给新对话快速接手）

最后更新：2026-06-02
用途：换新对话时，先读本文件 + `feature_status.md` + `product_backlog.md`，即可无缝接手。

---

## 1. 项目与角色
- **项目**：TaxGlobal AI —— AI 驱动的美国税务计算与合规平台(U.S.-first MVP)。核心卖点:**每个税额可追溯到法条、可审计、不伪装确定性**。
- **分工**:
  - **Claude(我)**:规划(分步计划)+ **设计文档(每步一份、可溯源)** + code review + 数值查证 + **写 Codex prompt**。**不写业务代码、不提交、不合并。**
  - **Codex**:按我的设计/prompt 写代码、开 PR、**合并**。
  - **Shaw(用户)**:拍板产品决策。
- **最高原则**:**数值精确是第一要义**;不确定就明确标注、绝不给假数/假范围;税率/阈值只能来自 `data/`,引擎不裸写。

## 2. 工作方法(必读文档)
- `docs/engineering_process.md` — 6 阶段流程 + 每步卡点
- `docs/coding_standards.md` — 写码规范
- `docs/code_review_checklist.md` — 我评审用的 5 维清单 + **标签 `[Blocker]/[Major]/[Minor]/[Nitpick]`**
- `docs/feature_status.md` — **实时功能状态总表(每步合并后我更新)**
- `docs/product_backlog.md` — 需求台账 REQ-001..011
- 每步:`docs/stepN_design_*.md`(设计) + `docs/stepN_*.md`(交付记录)

**我的 review 流程**:同步到 PR commit → 读代码 → **独立跑**(`python -m unittest discover -s tests`、`ruff check engine backend tests`、`pip-audit -r backend/requirements.txt`、`powershell -ExecutionPolicy Bypass -File tests\validate_step1_data.ps1`、`git diff --check`)→ **独立重算关键税额**(不信 PR 描述)→ 必要时 headless 复现 API/前端调用 → 按标签给结论。
- Python 解释器:`C:\Users\shawx\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`,`$env:PYTHONPATH=仓库根`。

## 3. 当前进度(main)
**已合并**:Step 0(基线)、1(数据)、1.1(资本利得)、1.2(CA/NY 累进州税)、1.3(QBI 数据)、2(引擎)、2.1(SE+Nexus)、2.2(crypto)、2.3(RSU)、2.4(QBI 引擎)、3(黄金测试+CI)、4(FastAPI)、5(前端接收入税)、5.1(hardening)、5.2(RSU 前端)、5.3(FEIE 前端)。
**在合/刚合**:Step 1.4(州税基数据,PR #13,我已 review 通过)。

### 引擎函数(纯函数、Decimal、读 JSON、带 citations/assumptions)
✅ bracket_tax, federal_income_tax, fica_tax, self_employment_tax, feie_estimate, state_income_tax(CA/NY 累进+10州), nexus_estimate, crypto_gain_estimate, rsu_tax_estimate, qbi_deduction
⬜ **income_tax_summary(下一步,见 §5)**

### 数据(`data/tax_years/2025/`)
us_federal, us_fica, us_feie, us_states(10 州;CA/NY 累进;5 个所得税州含 `tax_base`), us_nexus, us_capital_gains, us_qbi。来源全部归档在 `data/sources/us/2025/raw/` + `source_manifest.json`(hash 校验)。

### 后端 / 前端
- FastAPI `/calc/*`(8 接口 + /health),状态映射:ok/not_covered=200、invalid_input/校验=422、异常=500(不泄漏)、每响应带 X-Request-ID、CORS 走 `TAXGLOBAL_CORS_ORIGINS`。
- 前端 `frontend/index.html`(工作副本,已与根 `index.html` 分家;**根目录冻结,hash 恒为 `833508998A7FF1C783646E5E8B35E8C66AB27AE5FF88193318C2A1F2007B4B69`,每步必查未变**)。
- 已接后端的前端模块:**个人所得税(联邦+FICA+州)、RSU、FEIE**。
- 仍跑前端原型假算(待接):**自雇 calcSE、加密 calcCrypto、Nexus、6国对比 calcTreaty**;这些还在用过时硬编码 `caStateTax/nyStateTax`(REQ-003)。

## 4. 关键税务结论(已查证,用于下游)
- **自雇交两层联邦税 + 州税**:① SE 税(§1401:SS 12.4%@176100 + Medicare 2.9% + 附加 0.9%);② 联邦所得税(净利润 − ½SE − QBI − 标准扣除);③ 州税。NIIT **不**适用积极自雇。详见 `docs/tax_rules_self_employment.md`。
- **QBI(§199A)**:20%,2025 阈值 197300单/394600 MFJ(QSS 归 All-Other=197300),上限 247300/494600;只减所得税不减 SE 税。
- **各州税基不同**(精确算州税的关键):CA/NY/GA 起点=联邦AGI − 州标准扣除(CA 5706/11412、NY 8000/16050/HOH11200、GA 12000/24000),均不认 QBI;IL=联邦AGI − 免税额2850/人;CO=联邦应税收入 + QBI加回。
- 资本利得 LTCG 2025:single 48350/533400、mfj 96700/600050 等;NIIT 3.8% 阈值 200k/250k/125k。

## 5. ⏭ 立即下一步:Step 2.5 revised — `income_tax_summary`(精确州税)
> 1.4 合并后做。把自雇各块串成**总税,联邦+SE+州全精确**。
计算链(Decimal,组合各引擎 _money 输出):
```
SE = self_employment_tax(net_profit, filing)
agi = max(0, net_profit + other_ordinary_income − SE.deductible_half_se_tax − se_health − retirement)
ded = deduction 或 us_federal.standard_deduction[filing]
taxable_before_qbi = max(0, agi − ded)
QBI = qbi_deduction(qbi=agi−other_ordinary_income, taxable_income=taxable_before_qbi, ...).deduction
taxable = max(0, taxable_before_qbi − QBI)
federal = bracket_tax(taxable, 联邦档[filing])      # 不调 federal_income_tax(),避免重复减标准扣除
# 州税(用 §3 的 tax_base,不再用联邦应税收入):
  start_from=federal_agi → state_base = agi − (州标准扣除[filing] 或 免税额×人数)
  start_from=federal_taxable_income(CO) → state_base = taxable + (QBI 若 qbi_addback)
  state = flat_rate×state_base 或 bracket_tax(state_base, 州档[filing])
total = SE.self_employment_tax + SE.additional_medicare_tax + federal + state
quarterly = total/4
```
**已手算校验值**(net 10万自雇 single):federal 8630.60;**CA 州税 4550.96**(= bracket_tax(92935.22−5706=87229.22, CA single));FL 州税 0 → 总税 22760.15(FL)。SE 税 14129.55。
诚实边界:各州**残余特定加减项/抵免/NY recapture**仍未建模 → assumptions 标注。
之后:Step 5.4 自雇前端接 income_tax_summary;再 5.5/5.6 接 crypto/nexus 前端。

## 6. Backlog(`product_backlog.md`)
REQ-001 收入分美国/海外｜002 档案→计算同步｜003 删前端 caStateTax/nyStateTax｜004 海外被动收入/FTC｜005 档案模型重构(身份≠收入类型)｜006 股票期权 NQSO/ISO/ESPP｜008 QBI(✅已由 2.4 实现)｜009 income_tax_summary(=下一步)｜010 自雇健保/退休扣除+季度预缴｜011 州级残余税基一致性(1.4 已做核心,残余待补)。
**待补记**:REQ-007 确定性 crypto 税务优化器(HIFO/FIFO/LIFO 选最省 + 税损收割 + 持有期临界);仅税务优化,**非投资建议**(投资量化属受监管的另一产品,明确不做)。

## 7. 约定与踩过的坑
- **未提交的 docs 会被 Codex 流程清掉**:每个 Codex prompt 第 0 步都要"保留并提交未跟踪 docs";被清过一次(后从 stash 恢复)。
- **根 index.html hash 不变**是每步硬性验收。
- PowerShell(cp1252)对中文/emoji 输出会崩 → 探针脚本用 ASCII 或 `$env:PYTHONIOENCODING="utf-8"`。
- Chrome 扩展(Claude in Chrome)时好时坏 → 前端验证常用 **headless**(httpx 复现页面的 API 调用序列 + 读渲染函数字段)。
- 开发服务器要重启才加载新代码(踩过 stale uvicorn 把 tax_year→500 误判)。
- `.gitattributes`:`data/sources/**/raw/** -text -diff -eol`(保官方归档字节,跨平台 hash 稳定)。
- `requirements.txt` 只放运行时;测试依赖(httpx)在 `requirements-dev.txt`;`pip-audit` 是 CI 阻塞项。
- Codex 报 "gpt-image-2 不存在" = Codex 自身图像模型配置问题,**与本项目无关**,别理它。
- 商业化:网页上线只需 域名+托管+HTTPS(不必上 App Store);注册域名/开发者账号/付款/法律免责 = Shaw 自己做,我做不了。
